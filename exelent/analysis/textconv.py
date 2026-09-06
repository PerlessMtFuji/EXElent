"""TXT → PY. Plik tekstowy z okna czatu jest z definicji zanieczyszczony,
więc ta ścieżka jest bardziej podejrzliwa niż reszta analizy."""

from __future__ import annotations

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
# Sama ETYKIETA ogrodzenia, bez backtickow. Czesc okien czatu kopiuje ja
# razem z kodem, a samych backtickow juz nie — zostaje gola linia "python"
# na gorze. Parser ja przyjmuje (to zwykle wyrazenie-nazwa), wiec plik
# wyglada na dobry az do chwili, w ktorej kompilator odrzuca to, co ta linia
# zepchnela w dol — najczesciej `from __future__ import`, ktory musi stac
# jako pierwszy. Wymagany znak nowej linii na koncu: bez niego w pliku nie
# ma nic poza sama etykieta.
_FENCE_LABEL = re.compile(r"^[ \t]*(?:python3?|py)[ \t]*\n", re.IGNORECASE)
# Numer linii: opcjonalne wciecie, cyfry, opcjonalny separator, a potem
# odstep i kod. Grupa 1 to WLASNIE ten pelny odstep — z jego najmniejszej
# szerokosci w calym pliku wyliczamy separator, zeby nie zjesc wciecia kodu
# (A05). Bez chciwego `[ \t]*` przed separatorem, inaczej odstep uciekalby do
# niego i grupa mierzylaby zawsze 1.
_LINE_NUMBER = re.compile(r"^[ \t]*\d+[:|.]?([ \t]+)(?=\S)")
_PROMPT = re.compile(r"^(?:>>>|\.\.\.) ?")

# Marker zwracany, gdy po zdjeciu otoczki nie zostaje zaden kod. Osobny od
# bledu skladni: to nie "popraw linie X", tylko "wklej program".
NO_CODE = "__no_code__"


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


def _strip_fence_label(text: str) -> tuple[str, bool]:
    """Zdejmuje osamotniona etykiete ogrodzenia z pierwszej linii.

    Tylko gdy stoi SAMA na linii — `python = 3` to prawdziwy kod i zostaje.
    Tylko gdy cos po niej zostaje: plik zlozony z samego slowa "python" nie
    jest kodem, ktoremu ta funkcja ma pomoc, a pusty wynik zbudowalby EXE,
    ktory nic nie robi.
    """
    body = text.lstrip("\n")
    match = _FENCE_LABEL.match(body)
    if match is None:
        return text, False
    rest = body[match.end() :]
    if not rest.strip():
        return text, False
    return rest, True


def _strip_line_numbers(text: str) -> tuple[str, bool]:
    lines = text.split("\n")
    meaningful = [ln for ln in lines if ln.strip()]
    if not meaningful:
        return text, False
    matches = [_LINE_NUMBER.match(ln) for ln in meaningful]
    hits = [m for m in matches if m is not None]
    if len(hits) / len(meaningful) < 0.7:
        return text, False

    # Separator = NAJMNIEJSZY odstep miedzy numerem a kodem w calym pliku.
    # `1 def f():` (odstep 1) i `2     return 1` (odstep 5) daja separator 1,
    # wiec z linii 2 zdejmujemy jeden znak, a cztery spacje wciecia zostaja.
    # Wczesniej `[ \t]{1,4}` zjadalo wciecie i `return` ladowalo w kolumnie 0.
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
    """Wykrywa mieszanie tabów i spacji we wcięciach różnych linii kodu.

    To nie jest zgadywanie głębokości wcięcia — sprawdzamy jedynie, jakie
    znaki występują w już istniejącym wcięciu. CPython nie zawsze zgłasza
    `TabError` dla takiego miksu (np. gdy taby i spacje trafiają do
    odrębnych, niezagnieżdżonych bloków), więc to jedyny sposób, by
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


def _apply_replacements(text: str) -> str:
    for bad, good in _REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text


def _expand_indent_tabs(text: str) -> str:
    """Zamienia taby na spacje WYLACZNIE we wcieciu (tabstop 8), nie w tresci.

    `text.expandtabs()` rozwijalo tez taby WEWNATRZ napisow — literal `'a\\tb'`
    zmienial znaczenie (A05). Tu ruszamy tylko biale znaki na poczatku linii,
    czyli rzeczywiste wciecie; reszta linii, lacznie z napisami, zostaje."""
    out: list[str] = []
    for line in text.split("\n"):
        body = line.lstrip(" \t")
        indent = line[: len(line) - len(body)]
        out.append(indent.expandtabs(8) + body)
    return "\n".join(out)


def _check_syntax(text: str) -> None:
    """Rzuca `SyntaxError`, jesli `text` nie jest poprawnym Pythonem.

    `compile(..., "exec")`, a NIE `ast.parse` — i to jest cala rzecz. `ast.parse`
    uruchamia sam parser (`PyCF_ONLY_AST`) i zatrzymuje sie przed kompilatorem,
    a czesc regul jezyka jest sprawdzana dopiero tam: `from __future__ import`
    poza poczatkiem pliku, `return` poza funkcja, `yield`/`await` w zlym
    miejscu, powtorzony argument. `ast.parse` przepuszcza je wszystkie.

    Ta luka nie byla kosmetyczna. Wystarczylo, ze czat skopiowal etykiete
    ogrodzenia bez samych backtickow — zostawala goła linia `python` na
    gorze, czyli poprawne wyrazenie, ktore spycha `from __future__` z
    pierwszej linii. Konwersja mowila "ok", PyInstaller kompilowal ten plik
    dopiero przy skladaniu PYZ, lapal `SyntaxError`, WYRZUCAL modul z paczki
    i konczyl z kodem 0 — a uzytkownik dostawal EXE, ktore wita go
    "ImportError: No module named <jego program>".
    """
    compile(text, "<exelent>", "exec")


def _fail(encoding: str, steps: list[str], exc: SyntaxError) -> ConversionResult:
    return ConversionResult(
        ok=False,
        encoding=encoding,
        steps=tuple(steps),
        error_line=exc.lineno,
        error_text=exc.msg,
    )


def convert_text_to_python(raw: bytes) -> ConversionResult:
    text, encoding = decode_bytes(raw)
    steps: list[str] = []

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 1. Zdejmowanie OTOCZKI z okna czatu i numeracji. To zmiany strukturalne —
    #    dotykaja rzeczy, ktore nie sa kodem — i nie ruszaja tresci programu.
    text, changed = _strip_fences(text)
    if changed:
        steps.append("fence")
    text, changed = _strip_fence_label(text)
    if changed:
        steps.append("fence_label")
    text, changed = _strip_line_numbers(text)
    if changed:
        steps.append("line_numbers")
    text, changed = _strip_prompts(text)
    if changed:
        steps.append("prompts")

    text = text.strip("\n")

    # 2. Pusto po zdjeciu otoczki to nie program — osobny komunikat od bledu
    #    skladni ("wklej program", nie "popraw linie X").
    if not text.strip():
        return ConversionResult(
            ok=False, encoding=encoding, steps=tuple(steps), error_text=NO_CODE
        )

    # 3. Normalizacja WCIEC: taby -> spacje tylko we wcieciu, gdy mieszaja sie
    #    z spacjami. Nie dotyka tabow wewnatrz napisow.
    if _mixes_tabs_and_spaces(text):
        text = _expand_indent_tabs(text)
        steps.append("tabs")

    # 4. Poprawny Python zostaje BEZ heurystycznych zmian tresci. Literal
    #    `label = 'A—B…'` przechodzi nietkniety — wczesniej globalna podmiana
    #    znakow zmieniala jego wartosc (A05).
    try:
        _check_syntax(text)
        return ConversionResult(ok=True, code=text, encoding=encoding, steps=tuple(steps))
    except TabError:
        # CPython nie zawsze zglasza mieszanie tabow jako TabError przy kroku 3;
        # gdy jednak zglosi, rozwin wciecia i sprobuj jeszcze raz.
        fixed = _expand_indent_tabs(text)
        try:
            _check_syntax(fixed)
        except SyntaxError as exc:
            return _fail(encoding, steps, exc)
        if "tabs" not in steps:
            steps.append("tabs")
        return ConversionResult(ok=True, code=fixed, encoding=encoding, steps=tuple(steps))
    except SyntaxError as exc:
        # `as exc` znika po bloku (Python kasuje cel except), wiec przenosimy
        # blad do zwyklej zmiennej, zeby uzyc go, gdy naprawa nie pomoze.
        first_error = exc

    # 5. Kod sie nie kompiluje. TERAZ, jako NAPRAWA, probujemy podmiany znakow,
    #    ktore czat lubi psuc (cudzyslowy typograficzne uzyte jako ogranicznik
    #    napisu, twarda spacja, myslniki). Dla juz poprawnego kodu ten krok sie
    #    nie wykonuje, wiec nie moze zepsuc jego literalow.
    repaired = _apply_replacements(text)
    if repaired != text:
        try:
            _check_syntax(repaired)
        except SyntaxError as exc:
            return _fail(encoding, steps, exc)
        steps.append("normalize")
        return ConversionResult(ok=True, code=repaired, encoding=encoding, steps=tuple(steps))

    return _fail(encoding, steps, first_error)
