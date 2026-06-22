"""
Formatting & display helpers.

Public functions:
    - format_bytes       : human-readable byte count
    - parse_size         : reverse direction (e.g. '100MB' → bytes)
    - format_percent     : percentage formatting
    - get_color_codes    : ANSI palette, empty strings when not a TTY
    - has_unicode_support: probe stdout encoding for unicode glyphs
    - truncate_middle    : ellipsize in the middle
    - visible_len        : visible length, ignoring ANSI escapes
    - pad_visible        : pad a string to a target visible width
    - truncate_to_width  : respect ANSI codes when truncating
    - wrap_text          : word-wrap to a visible width
    - terminal_width     : cached terminal width probe
    - format_age / format_date: small string helpers

The module is intentionally dependency-free: only the standard library.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from typing import Dict, Optional


# --------------------------------------------------------------------------- #
#  Terminal probes
# --------------------------------------------------------------------------- #
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def has_unicode_support() -> bool:
    """Return True if stdout can render the unicode glyphs we use."""
    try:
        encoding = sys.stdout.encoding or "ascii"
        "┌─┬┐└┘├┤┴┼│✓█⠋·→←↑↓▒░▓◜◝◞◟◠◡—".encode(encoding)
        return True
    except Exception:
        return False


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")


def terminal_width(default: int = 120) -> int:
    """Return the current terminal width with sane fallbacks."""
    try:
        w = os.get_terminal_size().columns
        if w and w > 20:
            return w
    except Exception:
        pass
    # Honour SPACELYZER_WIDTH as an override
    env = os.environ.get("SPACELYZER_WIDTH")
    if env and env.isdigit() and 20 < int(env) < 1000:
        return int(env)
    return default


# --------------------------------------------------------------------------- #
#  Bytes / percentages
# --------------------------------------------------------------------------- #
def format_bytes(num_bytes, raw_bytes: bool = False) -> str:
    """Format a byte count as either a raw integer or a human string."""
    if raw_bytes:
        return f"{int(num_bytes)} B"
    if num_bytes is None or num_bytes < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB", "EB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} B"
            if size >= 100:
                return f"{size:.0f} {unit}"
            # Backwards-compat: keep the "1.0 KB" style for 1024
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} {units[-1]}"


def parse_size(size_str: str) -> int:
    """Parse a size string like '100MB' or '1.5 GB' into raw bytes."""
    if not size_str:
        return 0
    s = size_str.strip()
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$", s)
    if not m:
        raise ValueError(f"Invalid size format: '{size_str}'")
    number = float(m.group(1))
    unit = m.group(2).upper()
    multipliers: Dict[str, int] = {
        "": 1, "B": 1, "K": 1024, "KB": 1024, "KIB": 1024,
        "M": 1024 ** 2, "MB": 1024 ** 2, "MIB": 1024 ** 2,
        "G": 1024 ** 3, "GB": 1024 ** 3, "GIB": 1024 ** 3,
        "T": 1024 ** 4, "TB": 1024 ** 4, "TIB": 1024 ** 4,
        "P": 1024 ** 5, "PB": 1024 ** 5, "PIB": 1024 ** 5,
        "E": 1024 ** 6, "EB": 1024 ** 6, "EIB": 1024 ** 6,
    }
    if unit not in multipliers:
        raise ValueError(f"Unknown unit: '{unit}' in '{size_str}'")
    return int(number * multipliers[unit])


def format_percent(part: float, total: float, decimals: int = 1) -> str:
    if not total:
        return "0%"
    p = part / total * 100.0
    if decimals == 0:
        return f"{p:.0f}%"
    fmt = f"{{:.{decimals}f}}%"
    return fmt.format(p)


# --------------------------------------------------------------------------- #
#  Colors
# --------------------------------------------------------------------------- #
def get_color_codes() -> Dict[str, str]:
    """ANSI color palette, empty strings when not a TTY."""
    use_color = sys.stdout.isatty() or _env_truthy("SPACELYZER_FORCE_COLOR")
    if use_color:
        return {
            "blue": "\033[94m",
            "cyan": "\033[96m",
            "green": "\033[92m",
            "yellow": "\033[93m",
            "red": "\033[91m",
            "magenta": "\033[95m",
            "white": "\033[97m",
            "gray": "\033[90m",
            "bold": "\033[1m",
            "dim": "\033[2m",
            "underline": "\033[4m",
            "reset": "\033[0m",
        }
    return {k: "" for k in (
        "blue", "cyan", "green", "yellow", "red", "magenta", "white",
        "gray", "bold", "dim", "underline", "reset",
    )}


# --------------------------------------------------------------------------- #
#  Visible-length aware string helpers
# --------------------------------------------------------------------------- #
def visible_len(s: str) -> int:
    """Visible length of a string, ignoring ANSI SGR escape sequences."""
    return len(_ANSI_RE.sub("", s))


def pad_visible(s: str, width: int, align: str = "left") -> str:
    """Pad *s* with spaces so its visible length is exactly *width*."""
    pad = max(0, width - visible_len(s))
    if align == "right":
        return " " * pad + s
    if align == "center":
        l, r = pad // 2, pad - pad // 2
        return " " * l + s + " " * r
    return s + " " * pad


def truncate_middle(text: str, max_len: int) -> str:
    """Truncate *text* in the middle, preserving both ends."""
    if max_len <= 1 or len(text) <= max_len:
        return text
    if max_len < 4:
        return text[:max_len]
    keep = max_len - 1
    head = keep // 2
    tail = keep - head
    sep = "…" if has_unicode_support() else "..."
    return text[:head] + sep + text[-tail:]


def truncate_to_width(styled: str, max_width: int, placeholder: str = "…") -> str:
    """Truncate *styled* (which may contain ANSI codes) to *max_width*
    visible characters. ANSI codes are preserved.
    """
    if max_width <= 0:
        return ""
    if visible_len(styled) <= max_width:
        return styled
    # We can't safely chop bytes in the middle of an ANSI sequence, so
    # do a best-effort scan: walk the string copying visible characters
    # until we hit the limit, then append the placeholder and a reset.
    out: list = []
    visible = 0
    i = 0
    n = len(styled)
    while i < n and visible < max_width - 1:
        if styled[i] == "\x1b" and i + 1 < n and styled[i + 1] == "[":
            # Copy the full SGR sequence verbatim
            j = i + 2
            while j < n and styled[j] not in "ABCDEFGHJKSTfmnsulh":
                j += 1
            if j < n:
                j += 1
            out.append(styled[i:j])
            i = j
            continue
        out.append(styled[i])
        visible += 1
        i += 1
    # Always end with a reset so any open styling is closed
    out.append(placeholder)
    if "\x1b" in styled:
        out.append("\x1b[0m")
    return "".join(out)


def wrap_text(text: str, width: int) -> str:
    """Word-wrap *text* to *width* (visible columns)."""
    if width <= 0 or visible_len(text) <= width:
        return text
    out_lines: list = []
    for line in text.splitlines() or [text]:
        if visible_len(line) <= width:
            out_lines.append(line)
            continue
        words = line.split(" ")
        current = ""
        for w in words:
            if not current:
                current = w
            elif visible_len(current) + 1 + visible_len(w) <= width:
                current = f"{current} {w}"
            else:
                out_lines.append(current)
                current = w
        if current:
            out_lines.append(current)
    return "\n".join(out_lines)


# --------------------------------------------------------------------------- #
#  Dates / ages
# --------------------------------------------------------------------------- #
def format_age(mtime: float, now: Optional[float] = None) -> str:
    """Format a mtime as 'X days ago' / 'X months ago' / 'X years ago'."""
    if not mtime:
        return "—"
    if now is None:
        import time as _time
        now = _time.time()
    delta = max(0.0, now - mtime)
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)} min ago"
    if delta < 86400:
        return f"{int(delta // 3600)} hr ago"
    days = delta / 86400.0
    if days < 30:
        return f"{int(days)} days ago"
    months = days / 30.0
    if months < 12:
        return f"{int(months)} mo ago"
    return f"{months / 12:.1f} yr ago"


def format_date(mtime: float) -> str:
    if not mtime:
        return "—"
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")