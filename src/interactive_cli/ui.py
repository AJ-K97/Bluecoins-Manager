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


def _menu_panel(title, lines=None, width=86):
    lines = list(lines or [])
    border = _style("+" + "-" * (width - 2) + "+", _Ansi.BLUE)
    title_text = f" {title} "
    title_pad = max((width - 2 - len(title_text)) // 2, 0)
    title_line = "|" + (" " * title_pad) + title_text + (" " * (width - 2 - title_pad - len(title_text))) + "|"
    title_line = _style(title_line, _Ansi.BOLD, _Ansi.CYAN)

    def row(text=""):
        return ("| " + text).ljust(width - 1) + "|"

    out = [border, title_line, _style(row(), _Ansi.BLUE)]
    for line in lines:
        out.append(_style(row(line), _Ansi.BLUE))
    out.append(_style(row(), _Ansi.BLUE))
    out.append(border)
    out.append("")
    return "\n".join(out)


def _ok(msg):
    print(_style(msg, _Ansi.GREEN, _Ansi.BOLD))


def _info(msg):
    print(_style(msg, _Ansi.CYAN))


def _warn(msg):
    print(_style(msg, _Ansi.YELLOW, _Ansi.BOLD))


def _err(msg):
    print(_style(msg, _Ansi.RED, _Ansi.BOLD))
