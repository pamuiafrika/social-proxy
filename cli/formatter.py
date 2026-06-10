from typing import List


def header(text: str):
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print(f"{'─' * 60}")


def row(label: str, value, width: int = 22):
    print(f"  {label:<{width}} {value}")


def table(headers: List[str], rows: List[List], col_widths: List[int] = None):
    if not col_widths:
        col_widths = [max(len(str(r[i])) for r in ([headers] + rows)) + 2 for i in range(len(headers))]
    sep = "  " + "  ".join("-" * w for w in col_widths)
    header_line = "  " + "  ".join(str(h).ljust(w) for h, w in zip(headers, col_widths))
    print(header_line)
    print(sep)
    for r in rows:
        print("  " + "  ".join(str(c).ljust(w) for c, w in zip(r, col_widths)))


def success(msg: str):
    print(f"  ✓ {msg}")


def error(msg: str):
    print(f"  ✗ {msg}")


def warn(msg: str):
    print(f"  ! {msg}")


def truncate(text: str, length: int = 60) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ")
    return text if len(text) <= length else text[:length - 1] + "…"
