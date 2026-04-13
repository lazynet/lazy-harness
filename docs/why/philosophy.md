# Philosophy

Five principles that decide what goes into `lazy-harness` and what stays out.

## 1. Separation of concerns

Each component has one job. Configs live in dotfiles (chezmoi, yadm, whatever). Personal knowledge lives in a vault. The framework itself is boring code that wires these together — it is not a kitchen sink. When a feature would blur a boundary, the answer is no.

The litmus test: can you describe the feature's responsibility in one sentence without using "and"? If not, it needs to be split or rejected.

## 2. Ship before perfect

An 80% implementation deployed on real use beats a 100% implementation on a feature branch. Every design decision is made **against the friction of current use**, not against imagined future use. Concretely:

- Release small, often. Trunk-based development.
- Dogfood immediately. Every new feature is used by the maintainer on day one.
- Reversible decisions are preferred over optimal ones. If we can roll it back in a day, we can try it today.

## 3. Aggressive simplicity

Three repeated lines are better than a premature abstraction. Abstractions earn their keep by removing real duplication, not by anticipating it. Config is TOML, not a DSL. Hooks are shell-callable, not a plugin API. The CLI is click, not a custom parser.

When a feature requires new abstractions, the abstraction is built **inside** the feature that needs it first, and only extracted when a second use case genuinely demands it.

## 4. No tech debt by accident

Debt that you chose deliberately (with an ADR) is fine. Debt that accumulated because nobody said no is not. Every PR that adds complexity without removing equivalent complexity gets a second look. "We'll clean it up later" is a commitment, and commitments get ADRs.

The [backlog file](https://github.com/lazynet/lazy-harness/blob/main/docs/backlog.md) exists specifically to make debt visible. If it is not written down, it does not count as known.

## 5. Code > docs > conversation

A decision that only lives in a conversation is a decision that will be forgotten. Decisions live in code first (made manifest by the implementation), docs second (explained for future readers), and conversation only as a last resort when neither of the above applies yet.

Docs are not optional for framework-level features. A feature without a docs page is not done.
