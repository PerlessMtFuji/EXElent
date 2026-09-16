"""TXT -> PY. Text copied from a chat window is contaminated by definition,
so this path is more suspicious than the rest of the analysis."""

from __future__ import annotations

import bisect
import io
import re
import tokenize

from exelent.models import CodeBlockSpan, ConversionResult

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
# A bare fence LABEL without backticks. Some chat windows copy it with the
# code but omit the backticks, leaving a bare "python" line at the top. The
# parser accepts it (usually as a name expression), so the file looks valid
# until the compiler rejects what that line pushed down — most often a
# `from __future__ import`, which must come first. A trailing newline is
# required: without it the file contains nothing beyond the label itself.
_FENCE_LABEL = re.compile(r"^[ \t]*(?:python3?|py)[ \t]*\n", re.IGNORECASE)
# Line number: optional indentation, digits, an optional separator, then
# whitespace and code. Group 1 is EXACTLY that full whitespace — use its
# smallest width across the file as the separator so code indentation is not
# consumed. There is no greedy `[ \t]*` before the separator; otherwise the
# whitespace would escape into it and the group would always measure 1.
_LINE_NUMBER = re.compile(r"^[ \t]*\d+[:|.]?([ \t]+)(?=\S)")
_PROMPT = re.compile(r"^(?:>>>|\.\.\.) ?")

# Marker returned when removing the wrapper leaves no code. Separate from a
# syntax error: the instruction is "paste a program", not "fix line X".
NO_CODE = "__no_code__"


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """Return (text, encoding_name). A BOM takes precedence over guessing."""
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


def _line_starts(text: str) -> list[int]:
    """Character offsets for line starts, used to map regex matches to lines."""
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _strip_fences(
    text: str, origins: list[int]
) -> tuple[str, list[int], bool, list[CodeBlockSpan]]:
    """Extract fenced code blocks and join them. Alongside the text, maintain
    `origins`: for every output line, its line number in the original. This is
    the key line-map step — blocks are scattered between chat prose, so their
    numbering jumps and an error would otherwise point to a nonexistent line.

    Also return the bounds of each block (B02) as (start, end) pairs in the
    original TXT numbering. When there is more than one block, the presentation
    layer shows their bounds and explains that they were joined in that order.
    """
    matches = list(_FENCE.finditer(text))
    if not matches:
        return text, origins, False, []
    starts = _line_starts(text)
    out_lines: list[str] = []
    out_origins: list[int] = []
    block_spans: list[CodeBlockSpan] = []
    for match in matches:
        content = match.group(1)
        first = bisect.bisect_right(starts, match.start(1)) - 1
        base = first + (len(content) - len(content.lstrip("\n")))
        stripped = content.strip("\n")
        line_count = stripped.count("\n") + 1 if stripped else 0
        for offset, line in enumerate(stripped.split("\n")):
            out_lines.append(line)
            idx = base + offset
            out_origins.append(origins[idx] if idx < len(origins) else origins[-1])
        if line_count > 0:
            start_orig = origins[base] if base < len(origins) else origins[-1]
            end_idx = base + line_count - 1
            end_orig = origins[end_idx] if end_idx < len(origins) else origins[-1]
            block_spans.append(CodeBlockSpan(start_line=start_orig, end_line=end_orig))
    return "\n".join(out_lines), out_origins, True, block_spans


def _strip_fence_label(text: str, origins: list[int]) -> tuple[str, list[int], bool]:
    """Remove a lone fence label from the first line.

    Only when it stands ALONE on the line — `python = 3` is real code and stays.
    Only when content remains after it: a file containing only the word
    "python" is not code this function should help, and an empty result would
    build an EXE that does nothing.
    """
    lead = len(text) - len(text.lstrip("\n"))
    body = text[lead:]
    match = _FENCE_LABEL.match(body)
    if match is None:
        return text, origins, False
    rest = body[match.end() :]
    if not rest.strip():
        return text, origins, False
    # Removed `lead` blank lines from the top plus one label line.
    return rest, origins[lead + 1 :], True


def _strip_line_numbers(text: str) -> tuple[str, bool]:
    lines = text.split("\n")
    meaningful = [ln for ln in lines if ln.strip()]
    if not meaningful:
        return text, False
    matches = [_LINE_NUMBER.match(ln) for ln in meaningful]
    hits = [m for m in matches if m is not None]
    if len(hits) / len(meaningful) < 0.7:
        return text, False

    # Separator = the SMALLEST gap between the number and code in the file.
    # `1 def f():` (gap 1) and `2     return 1` (gap 5) yield separator 1, so
    # line 2 loses one character while its four indentation spaces remain.
    # Previously `[ \t]{1,4}` consumed indentation and put `return` in column 0.
    sep = min(len(m.group(1)) for m in hits)
    prefix = re.compile(r"^([ \t]*)\d+[:|.]?[ \t]{" + str(sep) + "}")
    return "\n".join(prefix.sub(r"\1", ln) if _LINE_NUMBER.match(ln) else ln for ln in lines), True


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
    """Detect tabs and spaces mixed across indentation of different code lines.

    This does not guess indentation depth — it only checks which characters
    occur in existing indentation. CPython does not always report `TabError`
    for such a mix (for example when tabs and spaces appear in separate,
    unnested blocks), so this is the only way to catch it before conversion.
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


# Tokens whose CONTENT repair must not touch: strings and text portions of
# f-strings. FSTRING_MIDDLE exists since 3.12 — protect it because
# `{expression}` inside an f-string is ordinary code (separate tokens), where
# replacement is acceptable.
_PROTECTED_TOKENS = frozenset(
    {tokenize.STRING}
    | ({tokenize.FSTRING_MIDDLE} if hasattr(tokenize, "FSTRING_MIDDLE") else set())
)


def _protected_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) offsets of characters belonging to string literals.

    The tokenizer stops at the FIRST broken delimiter, so this yields literals
    BEFORE that location — exactly those repair must not touch.
    `label = 'A—B…'` is a valid STRING; its dash and ellipsis are content, not
    delimiters, so global replacement has no place here."""
    line_starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            line_starts.append(i + 1)

    spans: list[tuple[int, int]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in _PROTECTED_TOKENS:
                start = line_starts[tok.start[0] - 1] + tok.start[1]
                end = line_starts[tok.end[0] - 1] + tok.end[1]
                spans.append((start, end))
    except (tokenize.TokenError, SyntaxError, ValueError):
        # A broken delimiter stops the tokenizer — keep protecting the literals
        # collected so far and leave the rest to repair.
        pass
    return spans


# DELIMITER characters: typographic quotes used instead of straight ones. The
# rest of `_REPLACEMENTS` (dashes, ellipsis, non-breaking spaces) are CONTENT
# characters. The distinction matters: repair a delimiter first, because only
# after closing the literal does its content (such as an internal dash) become
# protected.
_QUOTE_CHARS = frozenset("„“”«»‘’′")
_CONTENT_CHARS = frozenset(_REPLACEMENTS) - _QUOTE_CHARS

# Repair converges monotonically (each pass removes at least one bad character),
# so this is only a guard against an unexpected loop.
_MAX_REPAIR_PASSES = 10


def _compiles(text: str) -> bool:
    try:
        _check_syntax(text)
    except SyntaxError:
        return False
    return True


def _replace_outside(
    text: str, spans: list[tuple[int, int]], chars: frozenset[str]
) -> tuple[str, bool]:
    """Replace characters from `chars` OUTSIDE recognized literal content."""
    out: list[str] = []
    changed = False
    for i, ch in enumerate(text):
        if ch in chars and not any(s <= i < e for s, e in spans):
            out.append(_REPLACEMENTS[ch])
            changed = True
        else:
            out.append(ch)
    return "".join(out), changed


def _token_aware_repair(text: str) -> str:
    """Replace characters commonly damaged by chat, but ONLY outside recognized
    literal content. This replaces an earlier global substitution that changed
    the value of valid literals.

    Repair delimiters before content: `msg = ‘ok—now’` first receives straight
    quotes, and on the next tokenization the dash is inside a literal and stays
    untouched. When nothing else can be changed safely, return the current
    state and let the caller decide whether it is an error."""
    current = text
    for _ in range(_MAX_REPAIR_PASSES):
        if _compiles(current):
            return current
        spans = _protected_spans(current)
        candidate, changed = _replace_outside(current, spans, _QUOTE_CHARS)
        if not changed:
            candidate, changed = _replace_outside(current, spans, _CONTENT_CHARS)
        if not changed:
            return current
        current = candidate
    return current


def _expand_indent_tabs(text: str) -> str:
    """Replace tabs with spaces ONLY in indentation (tab stop 8), not content.

    `text.expandtabs()` also expanded tabs INSIDE strings, changing the meaning
    of the literal `'a\\tb'`. Here only leading whitespace — actual indentation
    — is changed; the rest of each line, including strings, remains intact."""
    out: list[str] = []
    for line in text.split("\n"):
        body = line.lstrip(" \t")
        indent = line[: len(line) - len(body)]
        out.append(indent.expandtabs(8) + body)
    return "\n".join(out)


def _check_syntax(text: str) -> None:
    """Raise `SyntaxError` if `text` is not valid Python.

    Use `compile(..., "exec")`, NOT `ast.parse` — that is the whole point.
    `ast.parse` runs only the parser (`PyCF_ONLY_AST`) and stops before the
    compiler, where some language rules are checked: `from __future__ import`
    away from the file start, `return` outside a function, `yield`/`await` in
    the wrong place, or a duplicate argument. `ast.parse` accepts all of them.

    This gap was not cosmetic. If chat copied a fence label without its
    backticks, a bare `python` line remained at the top: a valid expression
    that pushed `from __future__` off the first line. Conversion said "ok";
    PyInstaller compiled the file only while assembling PYZ, caught
    `SyntaxError`, DROPPED the module from the bundle, and exited with code 0 —
    leaving the user an EXE that opened with
    "ImportError: No module named <their program>".
    """
    compile(text, "<exelent>", "exec")


def _map_error_line(origins: list[int], lineno: int | None) -> int | None:
    """Linia z kompilatora (w KODZIE po konwersji) → linia w ORYGINALNYM TXT."""
    if lineno is not None and 1 <= lineno <= len(origins):
        return origins[lineno - 1]
    return lineno


def _fail(
    encoding: str, steps: list[str], exc: SyntaxError, origins: list[int]
) -> ConversionResult:
    return ConversionResult(
        ok=False,
        encoding=encoding,
        steps=tuple(steps),
        error_line=_map_error_line(origins, exc.lineno),
        error_text=exc.msg,
    )


def convert_text_to_python(raw: bytes) -> ConversionResult:
    text, encoding = decode_bytes(raw)
    steps: list[str] = []

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # `origins[k]` = line number in the original TXT for line k of the current
    # text. Carried through steps that shift numbering (fences, label, blank
    # lines at the edges); the remaining steps preserve line count 1:1, so the
    # map stays valid to the end.
    origins = list(range(1, text.count("\n") + 2))

    # 1. Remove WRAPPERS from chat and line numbering. These structural changes
    #    touch things that are not code and leave program content intact.
    #
    #    FIRST compile the entire input: a valid program is NOT stripped (B02).
    #    Without this gate, a fence INSIDE a string literal — a self-documenting
    #    program with a ```python block in a docstring — would be mistaken for
    #    a wrapper and extracted, replacing the real program with example
    #    content (ok=True). Indentation normalization and final validation below
    #    still apply: they preserve meaning rather than strip wrappers. Empty or
    #    whitespace-only input compiles as an empty module, so explicitly require
    #    content or this path would preempt the NO_CODE message below.
    code_blocks: list[CodeBlockSpan] = []
    if not (text.strip() and _compiles(text)):
        text, origins, changed, code_blocks = _strip_fences(text, origins)
        if changed:
            steps.append("fence")
        text, origins, changed = _strip_fence_label(text, origins)
        if changed:
            steps.append("fence_label")
        text, changed = _strip_line_numbers(text)
        if changed:
            steps.append("line_numbers")
        text, changed = _strip_prompts(text)
        if changed:
            steps.append("prompts")

    lead = len(text) - len(text.lstrip("\n"))
    trail = len(text) - len(text.rstrip("\n"))
    text = text.strip("\n")
    origins = origins[lead : len(origins) - trail] if trail else origins[lead:]

    # 2. Empty after wrapper removal is not a program — use a separate message
    #    from syntax errors ("paste a program", not "fix line X").
    if not text.strip():
        return ConversionResult(ok=False, encoding=encoding, steps=tuple(steps), error_text=NO_CODE)

    # 3. Normalize INDENTATION: tabs -> spaces only in indentation when mixed
    #    with spaces. Leave tabs inside strings untouched.
    if _mixes_tabs_and_spaces(text):
        text = _expand_indent_tabs(text)
        steps.append("tabs")

    # Report block bounds only when more than one was extracted (B02): one block
    # is a trivial extraction that needs no review. Empty code_blocks (no fences)
    # likewise need none.
    blocks = tuple(code_blocks) if len(code_blocks) > 1 else ()

    # 4. Valid Python remains WITHOUT heuristic content changes. The literal
    #    `label = 'A—B…'` passes untouched — global replacement used to change
    #    its value.
    try:
        _check_syntax(text)
        return ConversionResult(
            ok=True,
            code=text,
            encoding=encoding,
            steps=tuple(steps),
            line_map=tuple(origins),
            code_blocks=blocks,
        )
    except TabError:
        # CPython does not always report mixed tabs as TabError in step 3; when
        # it does, expand indentation and try again.
        fixed = _expand_indent_tabs(text)
        try:
            _check_syntax(fixed)
        except SyntaxError as exc:
            return _fail(encoding, steps, exc, origins)
        if "tabs" not in steps:
            steps.append("tabs")
        return ConversionResult(
            ok=True,
            code=fixed,
            encoding=encoding,
            steps=tuple(steps),
            line_map=tuple(origins),
            code_blocks=blocks,
        )
    except SyntaxError as exc:
        # `as exc` disappears after the block (Python clears the except target),
        # so move the error to a regular variable for use if repair fails.
        first_error = exc

    # 5. The code does not compile. NOW, as a REPAIR, replace characters that
    #    chat commonly corrupts (typographic quotes used as string delimiters,
    #    non-breaking spaces, dashes). This step never runs for already-valid
    #    code, so it cannot damage its literals.
    repaired = _token_aware_repair(text)
    if repaired != text:
        try:
            _check_syntax(repaired)
        except SyntaxError as exc:
            return _fail(encoding, steps, exc, origins)
        steps.append("normalize")
        return ConversionResult(
            ok=True,
            code=repaired,
            encoding=encoding,
            steps=tuple(steps),
            line_map=tuple(origins),
            code_blocks=blocks,
        )

    return _fail(encoding, steps, first_error, origins)
