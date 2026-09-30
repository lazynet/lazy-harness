"""Spans of a shell command that the shell provably treats as inert text.

The PreToolUse guards find command position with regexes that cannot see
quoting, so a `;`, `|` or backtick inside a quoted argument reads as a shell
operator and prose that merely quotes a dangerous command blocks like the
command itself. This module answers the narrow question those guards need:
which character ranges are data the shell will never run.

It fails closed. A span is inert only when both halves hold:

* **The shell does not interpret it** — single quotes; double quotes with no
  `$` or backtick; the body of a heredoc whose delimiter is quoted; and the
  body of that heredoc in the one substitution shape agents use for PR bodies
  and commit messages, `"$(cat <<'EOF' … EOF\\n)"`.
* **Nothing downstream runs it** — every simple command in the string is one
  whose arguments are text or paths, never code. `sh -c '…'`, `eval`, a pipe
  into an interpreter or a variable later evaluated keep the quoted text
  suspicious, because there it *is* a command.

Anything the scanner cannot classify with certainty — an unterminated quote,
command or process substitution, ANSI-C quoting, parameter expansion in braces,
a heredoc it cannot delimit — yields no spans at all, and the guard judges the
command exactly as it did before quoting was recognised.
"""

from __future__ import annotations

import re

Span = tuple[int, int]

# Commands whose arguments the shell hands over as text or paths and which
# execute none of them. Kept small on purpose: a wrongly listed command is an
# evasion, a missing one only a false positive.
_TEXT_COMMANDS = frozenset(
    {
        "cat",
        "cd",
        "cut",
        "echo",
        "grep",
        "head",
        "less",
        "more",
        "sort",
        "tail",
        "tee",
        "tr",
        "uniq",
        "wc",
    }
)
_GH_TEXT_SUBCOMMANDS = frozenset(
    {
        ("pr", "create"),
        ("pr", "edit"),
        ("pr", "comment"),
        ("pr", "review"),
        ("issue", "create"),
        ("issue", "edit"),
        ("issue", "comment"),
    }
)
# Not every git subcommand: `rebase --exec`, `submodule foreach`, `bisect run`
# and a `-c alias.x=!…` all run their argument.
_GIT_TEXT_SUBCOMMANDS = frozenset({"add", "commit"})

_DELIMITER = r"(?:'([A-Za-z0-9_.-]+)'|\"([A-Za-z0-9_.-]+)\"|\\([A-Za-z0-9_.-]+)|([A-Za-z0-9_.-]+))"
_HEREDOC_HEADER = re.compile(r"(-?)[ \t]*" + _DELIMITER + r"(?=[ \t\n;&|<>)]|$)")
_SUBSTITUTED_HEREDOC = re.compile(
    r"\"\$\(cat[ \t]+<<(-?)[ \t]*(?:'([A-Za-z0-9_.-]+)'|\"([A-Za-z0-9_.-]+)\")[ \t]*\n"
)
_SUBSTITUTION_CLOSE = re.compile(r"[ \t]*\)\"")


class _Unclassifiable(Exception):
    """The scanner met a construct it cannot prove inert."""


def inert_spans(command: str) -> tuple[Span, ...]:
    """Half-open ranges of `command` the shell treats as text nobody runs."""
    scanner = _Scanner(command)
    try:
        scanner.scan()
    except _Unclassifiable:
        return ()
    if not scanner.spans or not all(_is_text_command(words) for words in scanner.commands):
        return ()
    # A file written here could be a hook that `git add`/`commit` then runs.
    if scanner.writes and any(words[0] == "git" for words in scanner.commands):
        return ()
    return tuple(scanner.spans)


def starts_inert(position: int, spans: tuple[Span, ...]) -> bool:
    return any(start <= position < end for start, end in spans)


def mask(command: str, spans: tuple[Span, ...]) -> str:
    """Blank the inert spans, keeping offsets and line breaks where they were."""
    chars = list(command)
    for start, end in spans:
        for index in range(start, end):
            if chars[index] != "\n":
                chars[index] = "_"
    return "".join(chars)


def _is_text_command(words: list[str]) -> bool:
    name = words[0]
    if name == "printf":
        # `-v` takes a variable name, and bash evaluates an array subscript in
        # it as arithmetic -- command substitution included, even when quoted.
        return not any(word.startswith("-v") for word in words[1:])
    if name in _TEXT_COMMANDS:
        return True
    if name == "gh":
        return tuple(words[1:3]) in _GH_TEXT_SUBCOMMANDS
    if name == "git":
        args = words[1:]
        while len(args) >= 2 and args[0] == "-C":
            args = args[2:]
        return bool(args) and args[0] in _GIT_TEXT_SUBCOMMANDS
    return False


class _Scanner:
    """One pass over a command: its simple commands, its inert spans."""

    def __init__(self, command: str) -> None:
        self.text = command
        self.spans: list[Span] = []
        self.commands: list[list[str]] = []
        self.writes = False
        self._words: list[str] = []
        self._word: str | None = None
        self._heredocs: list[tuple[str, bool, bool]] = []

    def scan(self) -> None:
        text, i = self.text, 0
        while i < len(text):
            c = text[i]
            if c in " \t\r":
                self._end_word()
                i += 1
            elif c == "\\":
                if i + 1 >= len(text):
                    raise _Unclassifiable
                if text[i + 1] != "\n":
                    self._append(text[i + 1])
                i += 2
            elif c == "'":
                end = text.find("'", i + 1)
                if end < 0:
                    raise _Unclassifiable
                self._span(i + 1, end)
                self._append(text[i + 1 : end])
                i = end + 1
            elif c == '"':
                i = self._double_quoted(i)
            elif c == "`":
                raise _Unclassifiable
            elif c == "$":
                if text[i + 1 : i + 2] in ("(", "'", '"', "{"):
                    raise _Unclassifiable
                self._append(c)
                i += 1
            elif c == "#" and self._word is None:
                newline = text.find("\n", i)
                i = len(text) if newline < 0 else newline
            elif c == "\n":
                self._end_command()
                i = self._heredoc_bodies(i + 1)
            elif c in "<>" or (c == "&" and text[i + 1 : i + 2] == ">"):
                i = self._redirection(i)
            elif c in ";&|()":
                self._end_command()
                i += 1
            else:
                self._append(c)
                i += 1
        self._end_command()
        if self._heredocs:
            raise _Unclassifiable

    def _append(self, chars: str) -> None:
        self._word = (self._word or "") + chars

    def _span(self, start: int, end: int) -> None:
        if end > start:
            self.spans.append((start, end))

    def _end_word(self) -> None:
        if self._word is not None:
            self._words.append(self._word)
            self._word = None

    def _end_command(self) -> None:
        self._end_word()
        if self._words:
            self.commands.append(self._words)
            self._words = []

    def _double_quoted(self, i: int) -> int:
        text = self.text
        idiom = _SUBSTITUTED_HEREDOC.match(text, i)
        if idiom is not None:
            delimiter = idiom.group(2) or idiom.group(3)
            terminator = self._terminator(idiom.end(), delimiter, bool(idiom.group(1)))
            close = _SUBSTITUTION_CLOSE.match(text, terminator[1])
            if close is None:
                raise _Unclassifiable
            self._span(idiom.end(), terminator[0])
            self._append("<heredoc>")
            return close.end()
        end = i + 1
        while end < len(text) and text[end] != '"':
            end += 2 if text[end] == "\\" else 1
        if end >= len(text):
            raise _Unclassifiable
        body = text[i + 1 : end]
        if "`" in body or "$(" in body:
            raise _Unclassifiable
        if "$" not in body:
            self._span(i + 1, end)
        self._append(body)
        return end + 1

    def _redirection(self, i: int) -> int:
        text = self.text
        if text.startswith(("<(", ">("), i):
            raise _Unclassifiable
        self._end_word()
        if text.startswith("<<<", i):
            self._words.append("<<<")
            return i + 3
        if text.startswith("<<", i):
            header = _HEREDOC_HEADER.match(text, i + 2)
            if header is None:
                raise _Unclassifiable
            delimiter = next(g for g in header.groups()[1:] if g is not None)
            quoted = header.group(5) is None
            self._heredocs.append((delimiter, quoted, bool(header.group(1))))
            self._words.append("<<")
            return header.end()
        end = i + 1
        while end < len(text) and text[end] in "<>&|":
            end += 1
        operator = text[i:end]
        if ">" in operator:
            self.writes = True
        self._words.append(operator)
        return end

    def _heredoc_bodies(self, start: int) -> int:
        for delimiter, quoted, strip_tabs in self._heredocs:
            body_end, after = self._terminator(start, delimiter, strip_tabs)
            if quoted:
                self._span(start, body_end)
            start = after
        self._heredocs = []
        return start

    def _terminator(self, start: int, delimiter: str, strip_tabs: bool) -> Span:
        """Where the body ends and where the text after its closing line starts."""
        text, line = self.text, start
        while line < len(text):
            newline = text.find("\n", line)
            end = len(text) if newline < 0 else newline
            candidate = text[line:end]
            if (candidate.lstrip("\t") if strip_tabs else candidate) == delimiter:
                return line, (len(text) if newline < 0 else newline + 1)
            if newline < 0:
                break
            line = newline + 1
        raise _Unclassifiable
