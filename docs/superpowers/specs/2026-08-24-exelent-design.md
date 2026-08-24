# EXElent — dokument projektowy

**Data:** 2026-08-24
**Status:** zatwierdzony, gotowy do planu implementacji

## 1. Cel

EXElent zamienia katalog z plikami kodu (głównie Python) w gotowy plik `.exe`
dla systemu Windows. Odbiorcą jest osoba nietechniczna — w szczególności ktoś,
kto pisze programy przy pomocy AI i nie zna terminala, pip-a ani PyInstallera.

Kryterium sukcesu: użytkownik bez zainstalowanego Pythona pobiera jeden plik,
przeciąga katalog z kodem i po kilku minutach ma działający EXE — bez czytania
dokumentacji i bez ani jednej komendy w konsoli.

Wyróżnikiem jest obsługa plików `.txt` zawierających kod: EXElent sam
rozpoznaje je, czyści i konwertuje na poprawne `.py`.

## 2. Decyzje fundamentalne

| Decyzja | Wybór | Uzasadnienie |
|---|---|---|
| Python u użytkownika | zakładamy, że **nie ma** | grupa docelowa nie instaluje Pythona; EXElent przynosi własny |
| Silnik środowiska | **uv** | jeden plik ~15 MB, pobiera przenośnego CPythona *z tkinterem i pip-em*, tworzy izolowane środowiska |
| Silnik pakujący | **PyInstaller** za interfejsem `BuildBackend` | dojrzały, bez kompilatora C; abstrakcja otwiera drogę do Nuitki |
| GUI | **PySide6 / Qt** | najwyższy sufit estetyczny, dobre wsparcie dla kreatora, postępu i logów |
| UX | **kreator 3 kroków** + zwinięte „Zaawansowane” | domyślne wartości działają, ale każde zgadnięcie da się poprawić |
| Zależności | **auto-wykrycie + zgoda jednym klikiem** | kod z AI nie ma `requirements.txt`; użytkownik widzi, co się pobiera |
| Języki UI | **PL i EN** od v1, domyślnie wg języka systemu | projekt ma żyć poza Polską |
| Licencja | **MIT** | maksymalna swoboda dla open source |

### Warianty odrzucone

- **Oficjalny embeddable Python z python.org** — nie zawiera tkintera ani pip-a.
  Tkinter to framework, w którym AI generuje większość okienkowych programów dla
  początkujących; ten wariant wysypałby się na najczęstszym przypadku użycia.
- **Cicha instalacja instalatora python.org** — wymaga uprawnień administratora,
  modyfikuje PATH i rejestr, koliduje z istniejącymi instalacjami.
- **Nuitka w v1** — wymaga kompilatora C (~1 GB dodatkowego pobrania),
  buduje wielokrotnie dłużej, częściej wymaga ręcznego strojenia.
- **Jeden przycisk bez opcji** — gdy heurystyka wybierze zły plik główny,
  użytkownik nie ma jak tego naprawić i utyka bez wyjścia.

## 3. Architektura

### Zasada naczelna

Cała logika domenowa żyje w czystym Pythonie i **nie importuje Qt**. GUI jest
cienką skorupą wołającą rdzeń. Zależności są jednokierunkowe: `ui` → rdzeń,
nigdy odwrotnie.

Zysk jest praktyczny: heurystyki wykrywania i konwersja TXT są testowane na
setkach przypadków bez uruchamiania okna, a projekt zyskuje CLI
(`exelent build ./kod`) niemal za darmo.

### Kontrakt między warstwami

Trzy niemutowalne struktury danych stanowią cały interfejs:

```
katalog → [Analiza] → ProjectAnalysis → [Plan] → BuildPlan → [Build] → BuildResult
                            ↑                        ↑
                   "co zrozumiałem"        "co użytkownik poprawił"
```

- `ProjectAnalysis` — wynik zgadywania, z poziomem pewności każdego pola.
  Może być błędny i musi być nadpisywalny.
- `BuildPlan` — `ProjectAnalysis` po przejściu przez krok 2 kreatora.
  Build nigdy nie zgaduje; dostaje gotowy plan.
- `BuildResult` — ścieżka wyniku, rozmiar, czas, ostrzeżenia, log.

### Moduły

| Moduł | Odpowiedzialność | Zależy od |
|---|---|---|
| `exelent/analysis/` | skan katalogu: plik główny, typ aplikacji, pliki danych, importy | stdlib |
| `exelent/analysis/textconv.py` | TXT → PY: kodowanie, fence'y markdown, walidacja składni | stdlib |
| `exelent/deps/` | mapa `moduł → paczka PyPI`, odsiew biblioteki standardowej | stdlib |
| `exelent/runtime/` | bootstrap `uv`, pobranie CPythona, izolowane środowisko builda | subprocess |
| `exelent/build/` | interfejs `BuildBackend`, `PyInstallerBackend`, parsowanie postępu | runtime |
| `exelent/diagnostics/` | tłumaczenie błędów builda na zdania zrozumiałe dla laika | stdlib |
| `exelent/i18n/` | katalogi tłumaczeń PL/EN | stdlib |
| `exelent/ui/` | Qt: kreator, drag&drop, postęp, ekran wyniku | wszystko powyżej |

Żaden moduł nie sięga do wnętrza sąsiada — komunikacja wyłącznie przez
struktury z sekcji „Kontrakt między warstwami”.

### Cykl życia i stan na dysku

Aplikacja startuje natychmiast i **nie pobiera niczego, dopóki nie trzeba**.
Bootstrap uruchamia się dopiero przy pierwszym buildzie, z ekranem
„Przygotowuję narzędzia — to jednorazowe”.

Cały stan mieści się w `%LOCALAPPDATA%\EXElent\` i jest współdzielony między
projektami. EXElent **nie modyfikuje systemu**: żadnego PATH, rejestru ani
uprawnień administratora. Odinstalowanie to skasowanie pliku EXE i tego katalogu.

### Wątkowanie

Build trwa od minuty do kilku i nie może zamrozić okna. PyInstaller działa jako
podproces, jego wyjście czytane jest strumieniowo w osobnym wątku i mapowane na
fazy paska postępu (analiza importów → zbieranie → pakowanie).

Anulowanie musi realnie ubijać **drzewo procesów** (`taskkill /T`), ponieważ
PyInstaller uruchamia procesy potomne, które inaczej zostają sierotami.

Jednocześnie może trwać tylko jeden build — chroni to wspólny cache.

## 4. Interfejs użytkownika

Jedno okno ~900×620, natywna belka Windows, motyw ciemny/jasny za systemem,
trzy ekrany z animowanym przejściem.

**Ekran 1 — start.** Duże pole „przeciągnij tu folder z kodem”, alternatywnie
przycisk wyboru katalogu, pod spodem lista ostatnio używanych ścieżek
(maksymalnie 5, zwykły plik JSON w katalogu stanu — bez zapisanych konfiguracji
buildów). Bez menu, bez zakładek.

**Ekran 2 — „co zrozumiałem”.** Kluczowy ekran produktu. Wynik analizy podany
zdaniami, nie polami formularza; każda linia klikalna i edytowalna:

- Program główny: `main.py`
- To program w oknie / konsolowy
- Nazwa pliku wynikowego
- Ikona
- Lista wykrytych zależności z informacją, że zostaną pobrane
- Zwinięty panel „Zaawansowane”

Gdy dwaj najlepsi kandydaci na plik główny mają zbliżoną punktację, znacznik
pewności `✓` zmienia się w `?` — sygnał „sprawdź to” zamiast fałszywej pewności.

**Ekran 3 — budowanie i wynik.** Pasek postępu z nazwaną fazą, zwinięty log,
przycisk anulowania. Po zakończeniu: rozmiar pliku, `Pokaż w folderze`,
`Uruchom` oraz ostrzeżenie o fałszywych alarmach antywirusów.

## 5. Analiza katalogu

### Zbieranie plików

Rekurencyjny skan z wykluczeniem `.venv`, `venv`, `__pycache__`, `.git`,
`node_modules`, `build`, `dist`, `.idea`, `site-packages`. Skan jest przerywany
i zamieniany na ostrzeżenie po przekroczeniu **3000 plików lub 500 MB** — zamiast
cichego zawieszenia użytkownik dostaje pytanie, czy na pewno wskazał właściwy
katalog.

### Wejście, którego nie da się użyć

Trzy przypadki są rozstrzygane na ekranie 1, przed przejściem dalej:

- **Brak plików `.py` i brak `.txt` wyglądającego na kod** — komunikat, że w tym
  katalogu nie widać programu w Pythonie, z listą tego, co faktycznie znaleziono.
- **Kod w innym języku** (rozpoznany po dominujących rozszerzeniach: `.js`,
  `.java`, `.cs`) — uczciwa informacja, że v1 obsługuje wyłącznie Pythona.
- **Wiele niezależnych punktów wejścia** (kilka plików z `if __name__ ==
  "__main__"`, między którymi nie ma powiązań importowych) — pytanie, który
  program zbudować, zamiast wyboru za użytkownika.

### Wykrywanie pliku głównego

Najsilniejszym sygnałem jest **graf importów wewnątrz projektu** zbudowany z AST:
szukamy korzenia, czyli pliku, który importuje inne, ale sam nie jest importowany.

Na to nakładana jest punktacja:

- obecność `if __name__ == "__main__"`
- położenie w korzeniu katalogu
- typowe nazwy: `main`, `app`, `run`, `start`, `__main__`, nazwa katalogu
- wywołania startowe: `mainloop()`, `app.run()`, `.exec()`
- kara za prefiks `test_`

Wynikiem jest **posortowana lista kandydatów**, nie pojedynczy zwycięzca —
UI pokazuje ją w kolejności prawdopodobieństwa. Przy jednym pliku `.py`
heurystyka nie jest uruchamiana.

### Typ aplikacji

Import `tkinter`, `PySide6`, `PyQt5/6`, `kivy`, `pygame`, `customtkinter`, `wx`
oznacza program okienkowy. Obecność `input()` — konsolowy.

**Launcher jako obowiązkowy element każdego builda.** Program zbudowany bez
konsoli, który rzuci wyjątek, znika bez śladu — użytkownik widzi tylko, że „nic
się nie dzieje”. Dlatego punktem wejścia dla PyInstallera jest generowany
launcher, który uruchamia kod użytkownika w `try/except` i przy wyjątku pokazuje
okno z czytelnym komunikatem oraz przyciskiem „Kopiuj szczegóły”. Kod użytkownika
pozostaje nietknięty.

### Pliki danych i tryb wyjścia

Zasoby (obrazy, `.json`, `.csv`, czcionki, dźwięki) są dołączane do paczki.
Tryb wyjścia wynika z **kierunku dostępu do plików**:

- **Program tylko czyta** → pojedynczy plik EXE; launcher ustawia katalog roboczy
  na rozpakowaną paczkę. Względne ścieżki działają.
- **Program zapisuje** (`open(...,'w'/'a')`, `json.dump`, `to_csv`, `savefig`) →
  pojedynczy EXE zapisywałby do katalogu tymczasowego i dane ginęłyby po
  zamknięciu. Proponujemy folder z programem i wyjaśniamy dlaczego.

Decyzja jest widoczna i nadpisywalna w „Zaawansowanych”.

### Ikona

PyInstaller przyjmuje wyłącznie format `.ico`, a nietechniczny użytkownik ma
najczęściej `.png` z generatora obrazów. EXElent przyjmuje `.png`, `.jpg` i
`.ico`, a formaty inne niż `.ico` konwertuje sam, generując komplet rozmiarów
(16–256 px) — inaczej ikona wygląda źle na pasku zadań. Wymaga to `pillow` jako
zależności samego EXElent. Gdy w katalogu leży plik wyglądający na ikonę
(`icon.*`, `logo.*`), jest proponowany automatycznie.

### Zależności

AST daje listę importów. Odsiewane są: biblioteka standardowa
(`sys.stdlib_module_names` — lista pochodzi z samego Pythona, bez zgadywania)
oraz moduły lokalne. Importy w `try/except ImportError` traktowane są jako
opcjonalne i nie blokują builda. Istniejący `requirements.txt` ma pierwszeństwo
przed heurystyką.

**Mapa aliasów** (start: ~80 wpisów) tłumaczy nazwę importu na nazwę paczki:
`cv2`→`opencv-python`, `PIL`→`pillow`, `sklearn`→`scikit-learn`, `yaml`→`PyYAML`,
`bs4`→`beautifulsoup4`, `dotenv`→`python-dotenv`, `docx`→`python-docx`,
`fitz`→`PyMuPDF`, `serial`→`pyserial`, `win32com`→`pywin32`,
`Crypto`→`pycryptodome`. Nazwy spoza mapy trafiają do instalacji bez zmian.

## 6. Konwersja TXT → PY

Ścieżka celowo bardziej podejrzliwa niż reszta, ponieważ plik `.txt` z okna
czatu jest z definicji zanieczyszczony.

1. **Kodowanie** — kolejno: BOM (UTF-8, UTF-16 LE/BE) → UTF-8 → cp1250 →
   latin-1. Pokrywa polskiego Windowsa i Notatnik bez dodatkowych zależności.
2. **Normalizacja znaków** — cudzysłowy typograficzne → proste, półpauza →
   myślnik, twarda spacja → spacja, CRLF → LF. Znaki te wyglądają poprawnie,
   a Python ich nie przyjmuje.
3. **Zdejmowanie opakowań** — bloki markdown z ogrodzeniem z trzech grawisów:
   pobierana jest zawartość bloków, proza pomiędzy odrzucana. Numeracja linii
   wklejona z GitHuba lub czatu — obcinana, gdy wzorzec utrzymuje się w
   większości linii. Prompty `>>>` i `...` — usuwane.
4. **Walidacja** — `ast.parse()`. Powodzenie: zapis jako `.py`. Porażka: numer
   linii i czytelny komunikat, **build nie startuje**. Jedynym automatycznie
   naprawianym błędem jest mieszanka tabów i spacji, gdzie poprawka jest
   deterministyczna. Wcięć nie zgadujemy — po cichu zepsuty program jest gorszy
   niż uczciwy komunikat.
5. **Kwalifikacja plików** — `requirements.txt` trafia do zależności, nie do
   konwersji. Proza (`README.txt`, licencje) jest pomijana. Kryterium: plik musi
   wyglądać na kod.

## 7. Nienaruszalność katalogu użytkownika

Cały build odbywa się na **kopii** w `%LOCALAPPDATA%\EXElent\`. Konwersja TXT
zapisuje się na kopii, nigdy w oryginale. W katalogu użytkownika nie pojawiają
się `build/`, `dist/` ani pliki `.spec`.

To nie jest czystość dla samej czystości: odbiorca nie używa gita i nie ma jak
cofnąć zmian.

Jedynym artefaktem po stronie użytkownika jest folder `<Nazwa>-EXE` obok katalogu
źródłowego. Gdy tamta lokalizacja jest tylko do odczytu lub zsynchronizowana z
chmurą — zapis trafia na Pulpit.

## 8. Warunki brzegowe

### Antywirusy

EXE tworzone PyInstallerem bywają flagowane heurystycznie. To warunek brzegowy
do zarządzania, nie usterka do naprawienia:

- **UPX wyłączony** — kompresja drastycznie podnosi wykrywalność przy niewielkim
  zysku na rozmiarze.
- **Wykrywanie skasowania pliku w trakcie builda** — Defender potrafi usunąć
  artefakt w połowie procesu; komunikat musi to nazwać wprost.
- **Ekran wyniku zawiera wyjaśnienie i instrukcję dodania wyjątku** — użytkownik
  i tak to spotka; lepiej, żeby usłyszał od nas.

### Ścieżki

Katalog roboczy builda jest zawsze krótki i czysto ASCII
(`%LOCALAPPDATA%\EXElent\b\<hash8>`) — chroni przed limitem 260 znaków i przed
problemami narzędzi ze znakami spoza ASCII. Nazwa wynikowego EXE może zawierać
polskie znaki i spacje.

Pliki „tylko w chmurze” (OneDrive) wyglądają jak istniejące, a przy odczycie
blokują się na pobieraniu. Atrybut jest wykrywany, użytkownik proszony o
pobranie plików przed buildem.

### Sieć i zasoby

Dostępność internetu sprawdzana **przed** startem, nie w połowie. Po pierwszym
buildzie narzędzia są w cache i kolejne projekty bez nowych zależności budują
się offline. Proxy z podmianą certyfikatów jest rozpoznawane i nazywane, bez
prób automatycznego obejścia.

Wolne miejsce sprawdzane z góry. Wykrycie ciężkich paczek (`torch`,
`tensorflow`) uruchamia ostrzeżenie z szacunkiem rozmiaru i czasu **przed**
startem builda.

### Wersja Pythona

Domyślnie **3.12**, nie najnowsza dostępna. Świeże wydania przez pierwsze
miesiące nie mają gotowych paczek binarnych dla części popularnych bibliotek,
co u laika kończy się próbą kompilacji ze źródeł i porażką. Wybór wersji
znajduje się w „Zaawansowanych”.

### Kod, którego nie da się spakować

- **Dynamiczne importy** — gdy argument `importlib.import_module` jest literałem,
  dodawany jest jako ukryty import; gdy jest zmienną — ostrzeżenie.
- **Zewnętrzne narzędzia systemowe** (ffmpeg, tesseract) — nie wejdą do paczki;
  komunikat informuje, że odbiorca musi je mieć.
- **Serwery** (Flask, FastAPI) — zbudują się poprawnie, ale sprawiają wrażenie
  bezczynnych. Konsola zostaje zachowana, dodawana jest podpowiedź z adresem.
- **Sekrety w kodzie** — wykrycie `.env` lub wzorca klucza API uruchamia
  ostrzeżenie, że dane w EXE są odczytywalne.

### Powtarzalność

Wersje `uv` i PyInstallera są **przypięte na sztywno**, nigdy „najnowsza”.
Build ma zależeć od naszej decyzji, nie od tego, co wydano wczoraj.
Cache może ulec uszkodzeniu — UI udostępnia akcję „Napraw narzędzia”.

## 9. Obsługa błędów

Zasada: **użytkownik nigdy nie widzi surowego tracebacku jako głównego
komunikatu.**

Moduł `diagnostics` przechowuje wzorce dopasowywane do logów PyInstallera i
instalatora paczek; każdy wzorzec ma przypisane zdanie zrozumiałe dla laika oraz
sugerowaną akcję.

Błąd nierozpoznany daje ekran „Nie udało się — oto co wiem” z ostatnimi sensownymi
liniami logu i dwoma przyciskami: **Zapisz raport** oraz **Zgłoś na GitHubie** z
wypełnionym zgłoszeniem. Każde nierozpoznane pęknięcie staje się kandydatem na
nowy wzorzec w `diagnostics`.

## 10. Strategia testów

- **Jednostkowe** — korpus ~20 syntetycznych katalogów-projektów dla wykrywania
  pliku głównego i typu aplikacji; korpus celowo zanieczyszczonych plików `.txt`
  (BOM, cp1250, fence'y markdown, numeracja linii, cudzysłowy typograficzne)
  dla konwertera; testy mapy zależności.
- **Integracyjne „golden”** — kilka prawdziwych mini-projektów (okno tkinter,
  konsola z `input()`, program czytający JSON, program z pillow). Budowane
  naprawdę, z **uruchomieniem powstałego EXE** i weryfikacją wyniku. Wolne,
  oznaczone markerem, uruchamiane w CI na `windows-latest`.
- **GUI** — `pytest-qt`, minimalnie: przejścia kreatora i stany przycisków.

Testy integracyjne mają tu wagę większą niż zwykle: są jedynym dowodem, że
produkt faktycznie działa.

## 11. Zakres v1

**Wchodzi:** Windows 64-bit, Python 3.12, PyInstaller, kreator 3 kroków,
konwersja TXT, auto-wykrywanie zależności, launcher z obsługą awarii,
diagnostyka błędów, PL/EN, bootstrap bez Pythona w systemie.

**Nie wchodzi:** macOS i Linux, podpisywanie kodu certyfikatem, instalatory
MSI/Inno, obfuskacja, auto-aktualizacja, zarządzanie projektami (zapisane
profile buildów, wersjonowanie konfiguracji — lista ostatnich ścieżek z ekranu 1
to nie to samo), języki inne niż Python, równoległy wybór wielu wersji Pythona,
backend Nuitki.

Każda z tych pozycji da się dołożyć później i żadna nie jest potrzebna, by
nietechniczny użytkownik otrzymał działający plik EXE.
