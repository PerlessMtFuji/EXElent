"""TXT → PY. Plik tekstowy z okna czatu jest z definicji zanieczyszczony,
więc ta ścieżka jest bardziej podejrzliwa niż reszta analizy."""

from __future__ import annotations

import ast
import re

from exelent.models import ConversionResult

_ENCODINGS = ("utf-8", "cp1250", "latin-1")

_REPLACEMENTS = {
    "„": '"',
    "“": '"',
    "”": '"',
    "«": '"',
    "»": '"',
    "‘": "'",
    "’": "'",
    "′": "'",
    "–": "-",
    "—": "-",
    "−": "-",
    " ": " ",
    " ": " ",
    " ": " ",
    "…": "...",
}

_FENCE = re.compile(
    r"```[ \t]*(?:python|py|python3)?[ \t]*\n(.*?)(?:\n)?```", re.DOTALL | re.IGNORECASE
)
_LINE_NUMBER = re.compile(r"^[ \t]*\d+[ \t]*[:|.]?[ \t]{1,4}(?=\S)")
_PROMPT = re.compile(r"^(?:>>>|\.\.\.) ?")


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """Zwraca (tekst, nazwa_kodowania). BOM ma pierwszeństwo nad zgadywaniem."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


def _strip_fences(text: str) -> tuple[str, bool]:
    blocks = _FENCE.findall(text)
    if not blocks:
        return text, False
    return "\n".join(b.strip("\n") for b in blocks), True


def _strip_line_numbers(text: str) -> tuple[str, bool]:
    lines = text.split("\n")
    meaningful = [ln for ln in lines if ln.strip()]
    if not meaningful:
        return text, False
    hits = sum(1 for ln in meaningful if _LINE_NUMBER.match(ln))
    if hits / len(meaningful) < 0.7:
        return text, False
    return "\n".join(_LINE_NUMBER.sub("", ln) for ln in lines), True


def _strip_prompts(text: str) -> tuple[str, bool]:
    lines = text.split("\n")
    meaningful = [ln for ln in lines if ln.strip()]
    if not meaningful:
        return text, False
    hits = sum(1 for ln in meaningful if _PROMPT.match(ln))
    if hits / len(meaningful) < 0.7:
        return text, False
    return "\n".join(_PROMPT.sub("", ln) for ln in lines), True


def _mixes_tabs_and_spaces(text: str) -> bool:
    """Wykrywa mieszanie tabów i spacji we wcięciach różnych linii kodu.

    To nie jest zgadywanie głębokości wcięcia — sprawdzamy jedynie, jakie
    znaki występują w już istniejącym wcięciu. `ast.parse` nie zawsze
    zgłasza `TabError` dla takiego miksu (np. gdy taby i spacje trafiają
    do odrębnych, niezagnieżdżonych bloków), więc to jedyny sposób, by
    złapać ten przypadek przed dalszą konwersją.
    """
    has_tab = False
    has_space = False
    for line in text.split("\n"):
        if not line.strip():
            continue
        indent = line[: len(line) - len(line.lstrip(" \t"))]
        if "\t" in indent:
            has_tab = True
        if " " in indent:
            has_space = True
    return has_tab and has_space


def convert_text_to_python(raw: bytes) -> ConversionResult:
    text, encoding = decode_bytes(raw)
    steps: list[str] = []

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = text
    for bad, good in _REPLACEMENTS.items():
        normalized = normalized.replace(bad, good)
    if normalized != text:
        steps.append("normalize")
    text = normalized

    text, changed = _strip_fences(text)
    if changed:
        steps.append("fence")
    text, changed = _strip_line_numbers(text)
    if changed:
        steps.append("line_numbers")
    text, changed = _strip_prompts(text)
    if changed:
        steps.append("prompts")

    text = text.strip("\n")

    if _mixes_tabs_and_spaces(text):
        text = text.expandtabs(4)
        steps.append("tabs")

    try:
        ast.parse(text)
    except TabError:
        fixed = text.expandtabs(4)
        try:
            ast.parse(fixed)
        except SyntaxError as exc:
            return ConversionResult(
                ok=False,
                encoding=encoding,
                steps=tuple(steps),
                error_line=exc.lineno,
                error_text=exc.msg,
            )
        steps.append("tabs")
        text = fixed
    except SyntaxError as exc:
        return ConversionResult(
            ok=False,
            encoding=encoding,
            steps=tuple(steps),
            error_line=exc.lineno,
            error_text=exc.msg,
        )

    return ConversionResult(ok=True, code=text, encoding=encoding, steps=tuple(steps))
