import os
import sys
import asyncio
import itertools
from collections import deque
from typing import Iterable, List, Sequence

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

class _Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    BLUE = "\033[34m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"


def _style(text, *codes):
    return f"{''.join(codes)}{text}{_Ansi.RESET}"


def _supports_color():
    if os.getenv("NO_COLOR"):
        return False
    term = (os.getenv("TERM") or "").lower()
    if term in {"", "dumb"}:
        return False
    return sys.stdout.isatty()


_COLOR_ENABLED = _supports_color()
_DEFAULT_WIDTH = 96
_RECENT_ACTIONS = deque(maxlen=3)
_CURRENT_PATH = "Home"
_CURRENT_PENDING = 0
_DB_STATUS = "connected"
_KEY_HINT = "Keys: Enter=select | Esc=cancel | q=back | / search | s sort"


def _clear_view():
    if sys.stdout.isatty():
        # Clear screen and move cursor to home.
        print("\033[2J\033[H", end="")


def _menu_panel(title, lines=None, width=_DEFAULT_WIDTH):
    lines = list(lines or [])
    border = "+" + "-" * (width - 2) + "+"
    max_title_len = max(width - 6, 1)
    raw_title = (title or "").strip()
    if len(raw_title) > max_title_len:
        raw_title = raw_title[: max_title_len - 3] + "..."
    title_text = f" {raw_title} "
    title_pad = max((width - 2 - len(title_text)) // 2, 0)
    title_line = "|" + (" " * title_pad) + title_text + (" " * (width - 2 - title_pad - len(title_text))) + "|"

    def row(text=""):
        return ("| " + text).ljust(width - 1) + "|"

    # InquirerPy escapes ANSI control sequences in prompt messages.
    # Keep prompt panels plain-text to avoid visible escape characters.
    out = [border, title_line, row()]
    for line in lines:
        out.append(row(line))
    out.append(row())
    out.append(border)
    out.append("")
    return "\n".join(out)


def _render_menu_view(path, summary_lines=None, width=_DEFAULT_WIDTH, pending=None):
    global _CURRENT_PATH, _CURRENT_PENDING
    _CURRENT_PATH = path
    if pending is not None:
        try:
            _CURRENT_PENDING = int(pending)
        except Exception:
            _CURRENT_PENDING = 0
    _clear_view()
    print(_menu_panel(f"View: {path}", summary_lines or [], width=width))


def _menu_help_panel(tips_lines=None, width=_DEFAULT_WIDTH):
    status = f"{_CURRENT_PATH} | DB: {_DB_STATUS} | Pending: {_CURRENT_PENDING}"
    lines = [status, "", _KEY_HINT, ""]
    lines.extend(list(tips_lines or []))
    lines.append("")
    lines.append("Recent Actions:")
    if _RECENT_ACTIONS:
        lines.extend([f"- {item}" for item in list(_RECENT_ACTIONS)])
    else:
        lines.append("- none")
    return _menu_panel("Help & Tips", lines, width=width)


def _set_status(path=None, pending=None, db_status=None):
    global _CURRENT_PATH, _CURRENT_PENDING, _DB_STATUS
    if path is not None:
        _CURRENT_PATH = str(path)
    if pending is not None:
        try:
            _CURRENT_PENDING = int(pending)
        except Exception:
            _CURRENT_PENDING = 0
    if db_status is not None:
        _DB_STATUS = str(db_status)


def _record_action(text):
    entry = (text or "").strip()
    if entry:
        _RECENT_ACTIONS.appendleft(entry)


async def _pause(message="Press Enter to continue"):
    await inquirer.text(message=message, default="").execute_async()


async def _toast(msg, level="info", duration=0.9):
    _record_action(str(msg).strip())
    palette = {
        "ok": (_Ansi.GREEN, _Ansi.BOLD),
        "info": (_Ansi.CYAN,),
        "warn": (_Ansi.YELLOW, _Ansi.BOLD),
        "err": (_Ansi.RED, _Ansi.BOLD),
    }
    codes = palette.get(level, (_Ansi.CYAN,))
    text = _style(msg, *codes) if _COLOR_ENABLED else msg
    if not sys.stdout.isatty():
        print(text)
        return
    print(text, end="", flush=True)
    await asyncio.sleep(duration)
    print("\r\033[2K", end="", flush=True)


def _ok(msg, toast=False):
    if toast:
        return _toast(msg, level="ok")
    _record_action(str(msg).strip())
    print(_style(msg, _Ansi.GREEN, _Ansi.BOLD) if _COLOR_ENABLED else msg)


def _info(msg):
    print(_style(msg, _Ansi.CYAN) if _COLOR_ENABLED else msg)


def _warn(msg, toast=False):
    if toast:
        return _toast(msg, level="warn")
    _record_action(str(msg).strip())
    print(_style(msg, _Ansi.YELLOW, _Ansi.BOLD) if _COLOR_ENABLED else msg)


def _err(msg, toast=False):
    if toast:
        return _toast(msg, level="err")
    _record_action(str(msg).strip())
    print(_style(msg, _Ansi.RED, _Ansi.BOLD) if _COLOR_ENABLED else msg)


def _extract_choice_name(choice):
    if isinstance(choice, Choice):
        return str(choice.name)
    return str(choice)


def _is_separator(choice):
    return not isinstance(choice, Choice) and str(choice).strip().startswith("===")


async def _select_with_search(message, choices, threshold=12, **kwargs):
    selectable = [c for c in choices if not _is_separator(c)]
    if len(selectable) >= threshold:
        return await inquirer.fuzzy(message=message, choices=choices, **kwargs).execute_async()
    return await inquirer.select(message=message, choices=choices, **kwargs).execute_async()


def _format_table(headers: Sequence[str], rows: Sequence[Sequence[str]], width=_DEFAULT_WIDTH - 4) -> str:
    cols = len(headers)
    if cols == 0:
        return ""
    max_widths = [len(str(h)) for h in headers]
    for row in rows:
        for i in range(cols):
            val = str(row[i]) if i < len(row) else ""
            max_widths[i] = max(max_widths[i], len(val))
    total = sum(max_widths) + (3 * (cols - 1))
    if total > width:
        shrink = total - width
        while shrink > 0 and any(w > 8 for w in max_widths):
            idx = max(range(cols), key=lambda x: max_widths[x])
            if max_widths[idx] > 8:
                max_widths[idx] -= 1
                shrink -= 1
            else:
                break

    def clip(text, n):
        text = str(text)
        if len(text) <= n:
            return text.ljust(n)
        if n <= 3:
            return text[:n]
        return (text[: n - 3] + "...").ljust(n)

    header = " | ".join(clip(headers[i], max_widths[i]) for i in range(cols))
    divider = "-+-".join("-" * max_widths[i] for i in range(cols))
    body = []
    for row in rows:
        body.append(" | ".join(clip(row[i] if i < len(row) else "", max_widths[i]) for i in range(cols)))
    return "\n".join([header, divider] + body)


async def _paged_table_view(path, title, headers, rows, sort_options=None, page_size=12):
    sort_options = sort_options or [("default", lambda r: r)]
    sort_idx = 0
    sort_reverse = False
    query = ""
    page = 0

    while True:
        key_fn = sort_options[sort_idx][1]
        working = list(rows)
        if query:
            working = [r for r in working if query.lower() in " | ".join(map(str, r)).lower()]
        working.sort(key=key_fn, reverse=sort_reverse)

        total_pages = max((len(working) - 1) // page_size + 1, 1)
        page = max(0, min(page, total_pages - 1))
        start = page * page_size
        chunk = working[start : start + page_size]

        _render_menu_view(
            path=path,
            summary_lines=[
                f"{title}",
                f"Rows: {len(working)} / {len(rows)} | Page: {page + 1}/{total_pages}",
                f"Sort: {sort_options[sort_idx][0]} ({'desc' if sort_reverse else 'asc'}) | Filter: {query or 'none'}",
            ],
        )
        print(_format_table(headers, chunk))
        cmd = await inquirer.text(
            message="Table Command [Enter next | b prev | /term filter | s sort | r reverse | q back]:",
            default="",
        ).execute_async()
        cmd = (cmd or "").strip()
        if cmd == "":
            if page < total_pages - 1:
                page += 1
            else:
                page = 0
            continue
        if cmd.lower() in {"q", "quit", "back"}:
            return
        if cmd.lower() == "b":
            page = max(0, page - 1)
            continue
        if cmd.lower() == "s":
            sort_idx = (sort_idx + 1) % len(sort_options)
            page = 0
            continue
        if cmd.lower() == "r":
            sort_reverse = not sort_reverse
            page = 0
            continue
        if cmd.startswith("/"):
            query = cmd[1:].strip()
            page = 0
            continue


async def _confirm_destructive(path, action_label, typed_token="DELETE", details=None):
    details = list(details or [])
    _render_menu_view(
        path=path,
        summary_lines=[
            f"!!! DANGER: {action_label}",
            "This action is destructive and may be irreversible.",
            *details,
        ],
    )
    confirmed = await inquirer.confirm(
        message=f"Proceed with {action_label}?",
        default=False,
    ).execute_async()
    if not confirmed:
        return False
    typed = await inquirer.text(message=f"Type {typed_token} to confirm:").execute_async()
    return (typed or "").strip() == typed_token


async def _run_with_spinner(label, coro):
    spinner = itertools.cycle(["|", "/", "-", "\\"])
    task = asyncio.create_task(coro)
    try:
        while not task.done():
            frame = next(spinner)
            if sys.stdout.isatty():
                print(f"\r{label} {frame}", end="", flush=True)
            await asyncio.sleep(0.1)
        result = await task
    finally:
        if sys.stdout.isatty():
            print("\r\033[2K", end="", flush=True)
    return result
