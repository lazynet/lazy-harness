"""Render a view's return value to plain text for assertions.

The views used to print, so testing them meant capturing stdout — which is why
eight of the nine had no dedicated test. Now they return a renderable, and this
turns one into the text a terminal would show, with colour and hyperlinks off
so assertions read as the user's output rather than as escape sequences.
"""

from __future__ import annotations

import io
from typing import Any

from rich.console import Console


def render_to_text(renderable: Any, *, width: int = 120) -> str:
    buf = io.StringIO()
    Console(file=buf, width=width, force_terminal=False, no_color=True).print(renderable)
    return buf.getvalue()
