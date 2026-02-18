import os
import sys

from InquirerPy import inquirer

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


def _clear_view():
    if sys.stdout.isatty():
        # Clear screen and move cursor to home.
        print("\033[2J\033[H", end="")


def _menu_panel(title, lines=None, width=_DEFAULT_WIDTH):
    lines = list(lines or [])
    border = "+" + "-" * (width - 2) + "+"
    title_text = f" {title} "
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


def _render_menu_view(path, summary_lines=None, tips_lines=None, width=_DEFAULT_WIDTH):
    _clear_view()
    print(_menu_panel(f"View: {path}", summary_lines or [], width=width))
    print(_menu_panel("Help & Tips", tips_lines or [], width=width))


async def _pause(message="Press Enter to continue"):
    await inquirer.text(message=message, default="").execute_async()


def _ok(msg):
    print(_style(msg, _Ansi.GREEN, _Ansi.BOLD) if _COLOR_ENABLED else msg)


def _info(msg):
    print(_style(msg, _Ansi.CYAN) if _COLOR_ENABLED else msg)


def _warn(msg):
    print(_style(msg, _Ansi.YELLOW, _Ansi.BOLD) if _COLOR_ENABLED else msg)


def _err(msg):
    print(_style(msg, _Ansi.RED, _Ansi.BOLD) if _COLOR_ENABLED else msg)
