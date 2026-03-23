from __future__ import annotations


def parse_line_range(value: str, *, total_lines: int, allow_empty_insert: bool = False) -> tuple[int, int]:
    raw = value.strip()
    if raw == "":
        raise ValueError("Line range cannot be empty.")

    if "-" in raw:
        start_raw, end_raw = raw.split("-", 1)
    else:
        start_raw = raw
        end_raw = raw

    try:
        start = int(start_raw)
        end = int(end_raw)
    except ValueError as exc:
        raise ValueError("Line range must use integers like '3' or '10-14'.") from exc

    if start < 1 or end < 1 or end < start:
        raise ValueError("Line range must be positive and ordered.")

    if total_lines == 0 and allow_empty_insert and start == 1 and end == 1:
        return start, end

    if end > total_lines:
        raise ValueError(f"Line range exceeds file length ({total_lines} lines).")

    return start, end


def add_line_numbers(lines: list[str], *, start: int = 1) -> str:
    return "\n".join(f"{index}: {line}" for index, line in enumerate(lines, start=start))


def replace_lines(existing: list[str], start: int, end: int, new_lines: list[str]) -> list[str]:
    return [*existing[: start - 1], *new_lines, *existing[end:]]


def insert_before_line(existing: list[str], line_number: int, new_lines: list[str]) -> list[str]:
    if not existing and line_number == 1:
        return list(new_lines)
    return [*existing[: line_number - 1], *new_lines, *existing[line_number - 1 :]]


def insert_after_line(existing: list[str], line_number: int, new_lines: list[str]) -> list[str]:
    if not existing and line_number == 1:
        return list(new_lines)
    return [*existing[:line_number], *new_lines, *existing[line_number:]]


def delete_lines(existing: list[str], start: int, end: int) -> list[str]:
    return [*existing[: start - 1], *existing[end:]]


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def text_to_lines(text: str) -> list[str]:
    if text == "":
        return []
    return text.replace("\r\n", "\n").replace("\r", "\n").splitlines()


def lines_to_text(lines: list[str]) -> str:
    if not lines:
        return ""
    return "\n".join(lines) + "\n"
