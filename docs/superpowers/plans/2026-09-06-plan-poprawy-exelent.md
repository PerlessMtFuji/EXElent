# EXElent — plan poprawy niezawodności, tworzenia EXE i UX

Data: 2026-09-06. Status: plan do realizacji; poniższe pola nie oznaczają wdrożonych zmian.

## Stan realizacji (gałąź `feat/ui-poprawki`)

Rdzeń każdego zadania wdrożony i pokryty testami; pełny zestaw golden (15
realnych buildów EXE) przechodzi, `ruff` czysty, ~712 testów bez `slow`
zielonych. Poniżej co domknięte i co świadomie zostało jako zakres częściowy.

- **A01 — utrata danych (P0): zrobione.** `build/publish.py` publikuje pod wolną
  nazwą (`Program (2).exe`), kopia na wolumin docelowy → weryfikacja → atomowa
  zmiana nazwy; poprzednia wersja i dane nietknięte. Golden na ponowny build.
- **A02 — zakres builda (P1): zrobione.** `execute_build(plan,…)` buduje dokładnie
  plan, bez ponownej analizy; konwersje w planie (`BuildPlan.converted`).
- **A03 — entrypoint/importy (P1): zrobione.** `build/entrymodule.py` —
  kwalifikowana nazwa modułu i korzenie importów; golden dla `pkg/main.py` i
  `src/`. Domknięcie trybu jednoplikowego wciąga podmoduły (`pkg.child`),
  importy względne i `__init__.py`, bez wychodzenia ponad korzeń; golden na
  realnym EXE. Kolizja identycznych nazw modułów w różnych folderach bez pakietu
  → `module_name_collision` (WARNING). *Zostaje:* namespace packages, kolizje
  wielkości liter w obrębie jednego korzenia importów.
- **A04 — zasoby (P1): rdzeń.** `--add-data` zachowuje układ; ONEDIR z
  `--contents-directory .`; golden ONEDIR z innego cwd. Zapis przez
  `Path(...).open(mode)` czyta tryb z pozycji 0 (nie 1) → wymusza ONEDIR, więc
  dane nie giną w katalogu tymczasowym. *Zostaje:* kolizje zasobów przed
  buildem, lista zasobów w UI.
- **A05 — konwersja TXT (P1): rdzeń.** Poprawny Python bez zmian treści; taby
  tylko we wcięciu; numeracja zachowuje wcięcie; pusty wynik odrzucony. Naprawa
  niekompilującego się kodu jest świadoma tokenów: chroni treść rozpoznanych
  literałów (zwykłych, wielowierszowych, raw, bytes, części tekstowych
  f-stringów), naprawia ograniczniki przed treścią (`msg = ‘ok—now’` →
  `'ok—now'`, myślnik zostaje), a gdy granic literału nie da się pewnie
  rozpoznać (niesparowany cudzysłów) zwraca kontrolowany błąd zamiast zgadywać.
  `ConversionResult.line_map` wiąże każdą linię wyniku z linią oryginalnego TXT;
  zdejmowanie otoczki (ogrodzenia, etykieta, puste linie na brzegach) przesuwa
  numerację, więc `error_line` wskazuje teraz linię w pliku użytkownika, nie w
  wyciętym kodzie. *Zostaje:* podgląd/UI (podgląd oryginału, wyniku i listy
  zmian przed buildem) — z mapą linii jako podstawą.
- **A06 — ścieżki konwersji (P1): zrobione.** Klucz = ścieżka względna; kolizje
  `txt_collision`; golden na zagnieżdżony TXT.
- **A07 — zależności (P1): zrobione.** `packaging.Requirement` (wersje ze
  spacjami, markery dla Windows/3.12, extras, `-r`/`-c`), poprawne try/except.
  `pyproject.toml` (PEP 621 `[project].dependencies`) z pierwszeństwem
  `requirements.txt` przed pyproject; `dynamic`/Poetry/nieczytelny TOML spada do
  skanu importów. Cykl, brak pliku `-r` i nieczytelny pyproject idą jako `Issue`
  (WARNING). *Zostaje:* rozdział zadeklarowane vs wykryte importy (rozbieżności),
  Poetry `[tool.poetry]`, ręczne dopisanie hidden imports.
- **A08 — wiarygodny wynik (P1): rdzeń.** Nieudana wymagana paczka →
  `required_package_failed`, stop przed PyInstallerem. Zepsuty składniowo `.py`
  daje `py_syntax_error` (BLOCKER) w analizie — koniec „fałszywego sukcesu",
  symetrycznie do zepsutego TXT. *Zostaje:* walidacja źródeł docelowym
  interpreterem 3.12 (dziś `ast.parse` deweloperskim), rozróżnienie
  „utworzono/zweryfikowano".
- **A09 — anulowanie (P2): rdzeń.** Token w pobieraniu/tworzeniu środowiska
  (anulowalny `_stream_uv`, `kill_tree`); UI „Przerywanie…". *Zostaje:* token
  dla bootstrapu uv i publikacji.
- **A10 — responsywna analiza (P2): częściowo.** `_read_head` czyta tylko
  prefiks. *Zostaje:* analiza poza wątkiem Qt z request-id i anulowaniem.
- **A11 — preflight/szacunki (P2): rdzeń.** Preflight celuje w Python 3.12;
  szacunki normalizują nazwę (`pandas==2.2.3`). *Zostaje:* rozdział modeli
  transfer/artefakt w UI, zależności przechodnie/cache.
- **A12 — UI/UX (P2): rdzeń bugu.** `executable_path` w wyniku; „Uruchom" i
  „Pokaż w folderze" działają dla ONEDIR. *Zostaje:* podsumowanie przed
  buildem, ikony blokera/ostrzeżenia, przewijanie, log na żywo, audyt PL/EN.
- **A13 — struktura/sesja (P2): rdzeń.** Identyfikator sesji izoluje katalogi
  robocze dwóch instancji; `execute_build` w rdzeniu; wersja Pythona z planu.
  *Zostaje:* współdzielenie AST, ochrona wspólnego cache, skrócenie komentarzy.
- **A14 — testy/bramki (P1): w toku ciągłym.** Izolacja `LOCALAPPDATA` w testach
  UI; reprodukcja + kontrakt publiczny przy każdej naprawie; golden rozszerzone
  o realne uruchomienia. *Zostaje:* bootstrap 3.12 bez cache, ścieżki ze
  spacjami/znakami polskimi, błędy uprawnień/miejsca przez fixture'y, CI.

## Cel i zakres

EXElent ma przekształcać projekt Python lub kod skopiowany do TXT w działającą aplikację Windows, również dla osoby bez wiedzy programistycznej. Sukces powinien oznaczać spójny, kompletny artefakt odpowiadający wyborom użytkownika, a wszystkie ograniczenia muszą być widoczne przed budowaniem lub w jego wyniku.

Plan obejmuje problemy opisane w przeglądzie: ochronę danych, przepływ planu budowania, importy i zasoby, konwersję TXT, zależności, anulowanie, analizę projektu, preflight, szacunki, UI/UX oraz strukturę i testy. Dokument jest planem zmian; jego utworzenie nie zmienia działania aplikacji.

Główną logikę tworzenia EXE stanowi cały przepływ:

`analysis → planning/BuildPlan → workspace → runtime/env → build/pyinstaller + launcher → odbiór artefaktu → UI/CLI`.

[`textconv.py`](../../../exelent/analysis/textconv.py) odpowiada za przygotowanie kodu z TXT, więc jego błędy mogą zmienić zachowanie aplikacji jeszcze przed pakowaniem.

## Punkt odniesienia i dowody

W przeglądzie wykonano testy jednostkowe, reprodukcje wybranych błędów oraz dwa rzeczywiste buildy ONEDIR:

- Testy bez znacznika `slow`: 667 zaliczonych, 1 niezaliczony, 12 pominiętych. Test języka interfejsu przechodził po odizolowaniu ustawień użytkownika; przyczyną była zależność testu od lokalnego stanu.
- Wejście `pkg/main.py`: backend zgłosił sukces, a uruchomiony EXE zakończył się błędem `ImportError: No module named main`.
- Odczyt `config.json` i `assets/nested.json`: backend zgłosił sukces, ale EXE nie znajdował obu zasobów. Pliki trafiły do `_internal`, a zasób zagnieżdżony dodatkowo utracił ścieżkę `assets/`.
- Reprodukcja odbioru artefaktu potwierdziła usunięcie istniejącego pliku danych użytkownika we wcześniej utworzonym katalogu aplikacji.
- Reprodukcje potwierdziły zmianę literałów przez konwerter, utratę zakresu pojedynczego pliku w GUI, błędy parsowania zależności oraz problemy opisane w dalszych zadaniach.

Rzeczywiste buildy używały lokalnego Pythona 3.13.5 i PyInstallera 6.16.0. Nie zastępują pełnej walidacji docelowego Pythona 3.12 ani całej ścieżki bootstrapu. Wyniki pochodzą z przeglądu poprzedzającego ten dokument; nie są nowym uruchomieniem testów podczas pisania planu.

## Zasady realizacji

- Zachować granicę: rdzeń bez Qt; GUI prezentuje wyniki i wysyła polecenia.
- Błędy i ostrzeżenia przekazywać jako ustrukturyzowane `Issue`; dodać komunikaty PL i EN.
- Nie modyfikować źródłowego projektu. Konwersję i pakowanie wykonywać w osobnym katalogu sesji.
- Budować dokładnie zaakceptowany plan. Zmiana źródeł wymagająca innego planu prowadzi do ponownej analizy i przeglądu wyborów.
- Nie usuwać istniejących danych przy publikowaniu nowego artefaktu.
- Nie wykonywać wejściowego kodu podczas analizy i konwersji. Kompilacja składniowa nie uruchamia programu.
- Testy jednostkowe izolują ustawienia, katalogi aplikacji, procesy i sieć. Testy rzeczywistych EXE używają kontrolowanych projektów testowych.
- Przed każdą komendą Python/pytest/ruff/uv ustalić interpreter przez narzędzie środowiska PyCharm. Interpreter deweloperski i interpreter docelowego EXE traktować osobno.

## Kolejność i mapa problemów

P0: możliwość utraty danych. P1: niepoprawny EXE, zmiana programu lub fałszywy sukces. P2: odporność, UX i utrzymanie.

| ID | Problem | Priorytet | Zależności |
|---|---|---|---|
| A01 | Usuwanie poprzedniego ONEDIR i danych użytkownika | P0 | Brak |
| A02 | Utrata `single_file` i odtwarzanie planu w GUI | P1 | Brak |
| A03 | Niepoprawna nazwa modułu wejściowego i importy lokalne | P1 | A02 |
| A04 | Spłaszczanie zasobów i niezgodne katalogi uruchomienia | P1 | A02, A03 |
| A05 | Konwersja TXT zmienia literały i wcięcia | P1 | Brak |
| A06 | Kolizje i utrata ścieżek plików TXT → PY | P1 | A02, A05 |
| A07 | Utrata semantyki zależności | P1 | A02, A03 |
| A08 | Brak wymaganych pakietów ukryty za sukcesem | P1 | A07 |
| A09 | Anulowanie nie obejmuje całego procesu | P2 | A02 |
| A10 | Analiza blokuje GUI; limity i błędy I/O są niespójne | P2 | A02 |
| A11 | Niesprawny preflight i mylące szacunki | P2 | A07, A09 |
| A12 | Niespójny ekran wyniku i pozostałe problemy UX | P2 | A01–A11, zależnie od funkcji |
| A13 | Rozdzielenie odpowiedzialności i izolacja sesji | P2 | Częściowo razem z A02 |
| A14 | Testy regresji, rzeczywistych EXE i izolacja testów | P1 | Realizowane przy każdym zadaniu |

## A01. Bezpieczny odbiór i publikowanie artefaktu

Pliki: [`build/pyinstaller.py`](../../../exelent/build/pyinstaller.py), [`build/launcher.py`](../../../exelent/build/launcher.py), [`models.py`](../../../exelent/models.py).

Problem: `_collect_artifact` usuwa istniejący katalog docelowy przed przeniesieniem nowego. ONEDIR może zawierać bazę danych lub konfigurację zapisaną przez uruchomioną aplikację. Awaria przenoszenia może dodatkowo pozbawić użytkownika poprzedniej wersji.

- [ ] Domyślnie publikować kolejny build w nowej, unikalnej lokalizacji; nie nadpisywać automatycznie istniejącego katalogu ani pliku.
- [ ] Kopiować artefakt do katalogu tymczasowego na woluminie docelowym, sprawdzić kompletność, następnie finalizować zmianą nazwy w obrębie tego woluminu.
- [ ] Obsłużyć wyścig o nazwę docelową, zablokowany plik, brak miejsca i odmowę dostępu. W każdym przypadku zachować poprzedni artefakt.
- [ ] Rozróżnić katalog publikacji, ścieżkę EXE i pliki należące do builda. Usuwać wyłącznie pliki tymczasowe należące do bieżącej sesji.
- [ ] Pokazywać rzeczywistą lokalizację nowej wersji w UI i CLI. Nie przenosić automatycznie danych między wersjami bez zdefiniowanej polityki migracji.

Akceptacja i testy: istniejący `user-database.db` pozostaje bajtowo identyczny po udanym i nieudanym buildzie; błąd kopiowania nie uszkadza poprzedniego EXE; kolizja nazwy i równoległa publikacja nie powodują nadpisania.

## A02. Wykonywanie zaakceptowanego BuildPlan

Pliki: [`ui/worker.py`](../../../exelent/ui/worker.py), [`cli.py`](../../../exelent/cli.py), [`planning.py`](../../../exelent/planning.py), [`models.py`](../../../exelent/models.py).

Problem: worker przekazuje do `run_build` katalog główny i część parametrów, a CLI ponownie analizuje katalog. Wybranie jednego pliku może więc spowodować analizę i kopiowanie całego folderu.

- [ ] Wydzielić usługę `execute_build(plan, progress, cancel)` w rdzeniu. GUI przekazuje gotowy plan; CLI przygotowuje plan i wywołuje tę samą usługę.
- [ ] Utrwalić w planie zakres wejścia, entrypoint, źródła dodatkowe, konwersje, zasoby, zależności, tryb wyjścia, nazwę, ikonę, cel publikacji i docelowy interpreter.
- [ ] Przenieść metadane szacunków i pobierania w sposób powiązany z konkretnym planem, bez traktowania ich jako źródła listy zależności.
- [ ] Zdefiniować kontrolę zmian źródeł między analizą a kopiowaniem. Przy zmianie wpływającej na plan wymagać jego odświeżenia; nie rozszerzać zakresu po cichu.
- [ ] Testować GUI i CLI przez wspólny kontrakt usługi, bez uzależniania rdzenia od ekranu aplikacji.

Akceptacja i testy: budowanie `Downloads/chosen.py` nie kopiuje obcych skryptów z Downloads; zachowane są wszystkie zaakceptowane opcje; zmiana pliku po analizie daje czytelny wynik, a nie inny build bez informacji.

## A03. Entry point, pakiety i importy lokalne

Pliki: [`analysis/entrypoint.py`](../../../exelent/analysis/entrypoint.py), [`analysis/scanner.py`](../../../exelent/analysis/scanner.py), [`build/pyinstaller.py`](../../../exelent/build/pyinstaller.py), [`build/launcher.py`](../../../exelent/build/launcher.py).

Problem: `plan.entry.stem` sprowadza `pkg/main.py` do `main`. Sama nazwa pliku nie określa poprawnego modułu ani kontekstu importów. Domknięcie importów pojedynczego pliku nie obejmuje poprawnie wszystkich podmodułów i importów względnych.

- [ ] W analizie rozróżnić samodzielny skrypt, moduł pakietu i pakiet uruchamiany przez `__main__.py`.
- [ ] Wyznaczać jawnie korzenie importów i kwalifikowaną nazwę modułu; z tych samych danych generować launcher i argumenty PyInstallera.
- [ ] Obsłużyć zwykłe pakiety i układ `src/`. Dla nieobsługiwanych lub niejednoznacznych układów zwracać diagnostykę przed buildem.
- [ ] Uzupełnić analizę o `from pkg.child import ...`, importy względne oraz wymagane pliki `__init__.py`.
- [ ] Rozstrzygać kolizje identycznych nazw modułów w różnych folderach bez polegania na przypadkowej kolejności `sys.path`.

Akceptacja i testy: rzeczywiste EXE dla `main.py`, `pkg/main.py`, `python -m pkg` i projektu `src/` wykonują oczekiwaną czynność; działają importy względne i podmoduły; zakres pojedynczego pliku obejmuje potrzebne lokalne moduły.

## A04. Zasoby oraz katalogi odczytu i zapisu

Pliki: [`build/pyinstaller.py`](../../../exelent/build/pyinstaller.py), [`build/launcher.py`](../../../exelent/build/launcher.py), [`build/workspace.py`](../../../exelent/build/workspace.py), [`planning.py`](../../../exelent/planning.py).

Problem: wszystkie zasoby dostają cel `.` w `--add-data`, a ONEDIR uruchamia program z katalogu EXE, podczas gdy zasoby znajdują się w `_internal`.

- [ ] Zachować ścieżki względne zasobów, np. `assets/nested.json → assets/nested.json`, z uwzględnieniem ustalonego korzenia projektu lub pakietu.
- [ ] W planie zapisać mapowanie źródła zasobu na miejsce w paczce; wykrywać kolizje przed wywołaniem PyInstallera.
- [ ] Rozdzielić pojęcia zasobów w paczce, katalogu roboczego i trwałych danych użytkownika. Nie zakładać, że jedna zmiana `cwd` rozwiązuje wszystkie trzy potrzeby.
- [ ] Zdefiniować i wdrożyć jawną politykę zgodności dla skryptów z `open('config.json')`. Sprawdzić wariant zasobów obok EXE i wariant zasobów w `_internal`; wybrany wariant opisać i pokryć testami.
- [ ] Dla zasobów pakietów zachować zgodność z odczytem względem `__file__` i przez `importlib.resources`.
- [ ] Nie kierować trwałych zapisów do tymczasowego katalogu ONEFILE. Jeżeli aplikacja wymaga edytowalnych plików obok EXE, uwzględnić to w planie i opisie formatu wyniku.
- [ ] Pokazywać listę dołączonych zasobów oraz umożliwić korektę ich wyboru przed buildem.

Akceptacja i testy: ONEFILE i ONEDIR poprawnie czytają zasoby główne, zagnieżdżone i pakietowe, także gdy EXE uruchomiono z innego katalogu; dwa pliki o tej samej nazwie w różnych katalogach zachowują odrębność; zapisane dane przetrwają zamknięcie i kolejny build.

Punkt odniesienia: [dokumentacja uruchomienia aplikacji PyInstaller 6.16](https://pyinstaller.org/en/v6.16.0/runtime-information.html). W ONEDIR `sys._MEIPASS` wskazuje katalog `_internal`, a mapowanie zasobów musi odpowiadać sposobowi ich odczytu.

## A05. Konwersja TXT zachowująca znaczenie programu

Pliki: [`analysis/textconv.py`](../../../exelent/analysis/textconv.py), [`analysis/scanner.py`](../../../exelent/analysis/scanner.py), [`models.py`](../../../exelent/models.py), odpowiednie widoki i tłumaczenia.

Problem: globalne zamiany znaków i `expandtabs(8)` zmieniają również literały. Przykładowo `label = 'A—B…'` staje się inną wartością. Usuwanie numerów linii może usunąć właściwe wcięcia. Pusty blok kodu może zostać uznany za poprawny program.

- [ ] Najpierw sprawdzać składnię otrzymanego kodu. Poprawny Python zachować bez heurystycznych zmian jego treści.
- [ ] Rozdzielić dekodowanie, wydobycie kodu z otoczki czatu, ewentualną naprawę oraz walidację na czytelne etapy z raportem zmian.
- [ ] Zastąpić globalne podmiany analizą tokenów lub ostrożną analizą leksykalną. Chronić literały zwykłe, wielowierszowe, raw, bytes i części tekstowe f-stringów.
- [ ] Gdy uszkodzony tekst uniemożliwia pewne rozpoznanie granic literału, zwracać wskazanie problemu zamiast zgadywać zmianę znaczenia.
- [ ] Normalizować tabulatory wyłącznie w rzeczywistych wcięciach kodu; nie naruszać tabulatorów wewnątrz napisów ani ich wielowierszowej treści.
- [ ] Usuwać wyłącznie rozpoznany prefiks numeracji, zachowując pozostałe wcięcie. Niejednoznaczne prefiksy zgłaszać użytkownikowi.
- [ ] Odrzucać wynik pusty i złożony wyłącznie z otoczki czatu; ustalić osobny komunikat dla braku wykonywalnej treści.
- [ ] Stosować ten sam mechanizm rozpoznawania kodowania w skanerze i konwerterze, w tym UTF-8 BOM i UTF-16. Uszkodzony BOM lub sekwencja bajtów ma dawać diagnostykę, nie nieobsłużony wyjątek.
- [ ] Zachować mapę linii wyniku do oryginalnego TXT, aby błąd wskazywał miejsce, które użytkownik może odnaleźć.
- [ ] Dla wielu bloków kodu pokazać sposób ich połączenia; nie łączyć automatycznie alternatywnych wersji programu bez możliwości przeglądu.
- [ ] Przed buildem udostępnić podgląd oryginału, wyniku i listy zmian. Zachować oryginalny plik.
- [ ] Pozostawić `compile(..., 'exec')` jako kontrolę składni i dodać walidację przygotowanych źródeł docelowym Pythonem po utworzeniu środowiska, przed pakowaniem.

Akceptacja i testy:

- [ ] Poprawne programy zachowują treść literałów Unicode, tabulatory w napisach i napisy wielowierszowe; ponowna konwersja nie wprowadza dalszych zmian.
- [ ] `1 def f():`, `2     return 1`, `3 print(f())` po usunięciu numeracji zachowuje poprawny blok funkcji.
- [ ] Pusty fence, sam nagłówek, niedomknięty fence, błędne kodowanie i niejednoznaczny tekst dają kontrolowany rezultat.
- [ ] TXT w UTF-16 zostaje wykryty przez analizę projektu, a wskazanie błędu prowadzi do oryginalnej linii.
- [ ] Kod poprawny w interpreterze deweloperskim, ale niezgodny z docelowym 3.12, nie kończy się pozornie udanym EXE.

## A06. Ścieżki i kolizje konwertowanych źródeł

Pliki: [`analysis/project.py`](../../../exelent/analysis/project.py), [`build/workspace.py`](../../../exelent/build/workspace.py), [`models.py`](../../../exelent/models.py).

Problem: konwersje są indeksowane samą nazwą pliku, więc `pkg/helper.txt` może zostać zapisany jako `helper.py` w korzeniu. Zbieżne nazwy nadpisują się, podobnie jak istniejące pliki `.py`.

- [ ] Indeksować konwersje ścieżką względną do korzenia projektu i odtwarzać tę samą strukturę w kopii roboczej.
- [ ] Przed kopiowaniem wykrywać kolizje TXT/PY, zbieżność wielkości liter na Windows i wiele konwersji do tej samej ścieżki.
- [ ] Dla kolizji wymagać jednoznacznego wyboru wejścia lub zgłosić blocker; nie nadpisywać automatycznie istniejącego kodu.
- [ ] Walidować, że docelowe ścieżki pozostają w katalogu sesji.

Akceptacja i testy: `a/helper.txt` i `b/helper.txt` tworzą dwa osobne moduły; para `main.py`/`main.txt` daje widoczną kolizję; importy do konwertowanych modułów działają w rzeczywistym EXE.

## A07. Poprawna interpretacja zależności

Pliki: [`deps/resolve.py`](../../../exelent/deps/resolve.py), [`deps/aliases.py`](../../../exelent/deps/aliases.py), [`analysis/apptype.py`](../../../exelent/analysis/apptype.py), [`planning.py`](../../../exelent/planning.py).

Problem: własny regex gubi ograniczenia wersji ze spacjami i markery platformowe, ignoruje `-r`, a analiza `try/except` może uznać oba warianty importu za opcjonalne. Importy dynamiczne nie zasilają spójnie listy pakietów.

- [ ] Zastąpić uproszczony parser standardową obsługą specyfikacji wymagań lub przekazaniem zachowanych manifestów do resolvera uv.
- [ ] Zachować ograniczenia wersji, extras, markery, bezpośrednie referencje oraz pliki `-r`/`-c`; wykrywać cykle i brakujące pliki.
- [ ] Oceniać markery w kontekście docelowego Pythona i platformy, nie wyłącznie interpretera uruchamiającego EXElent.
- [ ] Ustalić pierwszeństwo głównego manifestu, manifestów zagnieżdżonych i `pyproject.toml`; nie wybierać pliku na podstawie kolejności skanowania.
- [ ] Rozdzielić zależności zadeklarowane od wykrytych importów. Pokazywać rozbieżności i nie uzupełniać ich bez śladu.
- [ ] Analizować gałęzie `try` i `except` osobno. Nie traktować dowolnego wyjątku z nazwą kończącą się na `Error` jako dowodu opcjonalnego importu.
- [ ] Dla `try: import orjson` / `except ImportError: import simplejson` zapewnić dostępność przynajmniej jednej właściwej gałęzi; nie odrzucać obu pakietów.
- [ ] Współdzielić rozpoznawanie stałych importów dynamicznych, np. `importlib.import_module('pandas')`, między resolverem i konfiguracją PyInstallera.
- [ ] Umożliwić ręczne dopisanie zależności i hidden imports dla przypadków niemożliwych do ustalenia statycznie.

Akceptacja i testy: `requests >= 2.0` zachowuje wersję; marker macOS nie instaluje pakietu na Windows; działają rekurencyjne manifesty, extras, fallback importu, stały import dynamiczny oraz projekt deklarujący zależności w `pyproject.toml`.

## A08. Wymagane pakiety i wiarygodny wynik budowania

Pliki: [`runtime/env.py`](../../../exelent/runtime/env.py), [`cli.py`](../../../exelent/cli.py), [`build/pyinstaller.py`](../../../exelent/build/pyinstaller.py), [`ui/screen_build.py`](../../../exelent/ui/screen_build.py).

Problem: po nieudanej instalacji wymaganych pakietów build może być kontynuowany, a ostrzeżenia znikają z ekranu sukcesu.

- [ ] Rozróżnić zależności wymagane, opcjonalne i nierozstrzygnięte w planie oraz wyniku instalacji.
- [ ] Zatrzymywać budowanie po nieudanej instalacji wymaganej zależności. Ewentualne próby instalacji pojedynczych pakietów mają ustalić przyczynę, nie zamaskować niekompletne środowisko.
- [ ] Sprawdzać gotowość środowiska i składnię źródeł docelowym interpreterem przed uruchomieniem PyInstallera.
- [ ] Przenosić ostrzeżenia ze wszystkich etapów do końcowego wyniku i prezentować je również po udanym pakowaniu.
- [ ] Rozróżniać „utworzono artefakt”, „utworzono z ostrzeżeniami” i „zweryfikowano uruchomienie”. Sam kod wyjścia 0 PyInstallera nie dowodzi poprawnego działania aplikacji.
- [ ] Sprawdzać strukturę odebranego artefaktu. Rzeczywiste uruchamianie wykonywać w golden tests; dla kodu użytkownika pozostawić jawny przycisk uruchomienia, bez automatycznego wykonywania go podczas analizy.

Akceptacja i testy: brak wymaganego pakietu nie daje sukcesu; brak opcjonalnego pakietu daje widoczną informację; ostrzeżenia pozostają dostępne w UI, CLI i raporcie; niekompletny artefakt zostaje odrzucony.

## A09. Anulowanie i zakończenie procesów

Pliki: [`runtime/bootstrap.py`](../../../exelent/runtime/bootstrap.py), [`runtime/env.py`](../../../exelent/runtime/env.py), [`runtime/procs.py`](../../../exelent/runtime/procs.py), [`build/workspace.py`](../../../exelent/build/workspace.py), [`build/pyinstaller.py`](../../../exelent/build/pyinstaller.py), [`ui/worker.py`](../../../exelent/ui/worker.py).

- [ ] Przekazywać wspólny token anulowania przez pobieranie, tworzenie środowiska, instalację, kopiowanie, pakowanie i publikację.
- [ ] Sprawdzać anulowanie między porcjami danych i plikami; operacje sieciowe i oczekiwanie na procesy ograniczyć timeoutami.
- [ ] Zapewnić obsługę procesu, który nic nie wypisuje, zamknął stdout, lecz nadal działa, lub pozostawił procesy potomne.
- [ ] Ujednolicić zamykanie drzewa procesów i ograniczyć również czas oczekiwania po próbie zakończenia.
- [ ] Sprzątać tylko bieżącą sesję. Anulowanie publikacji nie może uszkodzić poprzedniego artefaktu.
- [ ] W UI natychmiast pokazać stan „Anulowanie…”, zapobiec ponownym kliknięciom i zakończyć stanem anulowania zamiast błędem.

Akceptacja i testy: kontrolowane, zablokowane operacje na każdym etapie reagują na token i kończą się w ustalonym budżecie czasu; nie pozostają procesy potomne; GUI zachowuje responsywność; testy nie polegają na arbitralnym długim `sleep`.

## A10. Responsywna i ograniczona analiza projektu

Pliki: [`ui/app.py`](../../../exelent/ui/app.py), [`analysis/scanner.py`](../../../exelent/analysis/scanner.py), [`analysis/project.py`](../../../exelent/analysis/project.py), [`build/workspace.py`](../../../exelent/build/workspace.py).

- [ ] Przenieść analizę poza główny wątek Qt; prezentować stan pracy i umożliwić anulowanie.
- [ ] Dodać granicę obsługi błędów odczytu, dekodowania i dostępu do katalogów; zamieniać przewidywalne wyjątki na diagnostykę.
- [ ] Czytać wyłącznie potrzebny fragment przy rozpoznawaniu pliku, zamiast `read_bytes()` całego pliku przed obcięciem.
- [ ] Stosować te same wykluczenia i limity plików/bajtów w analizie, rozpoznawaniu obcych języków oraz materializacji.
- [ ] Kopiować zaakceptowany inwentarz planu. Nie wykonywać nieograniczonego `copytree` po analizie, która zatrzymała się na limicie.
- [ ] Przy przekroczeniu limitu pokazać konkretny problem i sposób zawężenia wejścia. Nie przedstawiać niepełnej analizy jako kompletnej.
- [ ] Obsłużyć usunięcie lub zmianę pliku podczas skanowania i kopiowania oraz katalogi z cyklicznymi dowiązaniami.
- [ ] Powiązać wyniki pracy w tle z identyfikatorem żądania, aby starsza analiza nie nadpisywała nowego wyboru.

Akceptacja i testy: duży projekt nie blokuje interakcji z oknem; brak uprawnień nie daje nieobsłużonego wyjątku; skanowanie i kopiowanie przestrzegają jednego zakresu; zmiana wyboru w czasie analizy nie wyświetla starych wyników.

## A11. Działający preflight i uczciwe szacunki

Pliki: [`ui/preflight.py`](../../../exelent/ui/preflight.py), [`deps/sizes.py`](../../../exelent/deps/sizes.py), [`ui/app.py`](../../../exelent/ui/app.py), [`runtime/env.py`](../../../exelent/runtime/env.py).

Problem: preflight wskazuje interpreter w `preflight-venv`, którego kod nie tworzy. Szacunki zależne od dokładnego klucza nie rozpoznają np. `pandas==2.2.3`, a rozmiar EXE bywa prezentowany jako wielkość pobierania.

- [ ] Korzystać z istniejącego i zweryfikowanego interpretera albo jawnie utworzyć środowisko preflight we właściwej fazie. Nie zakładać istnienia ścieżki.
- [ ] Rozróżnić stan bez uv, bez Pythona, offline, błąd resolvera, wynik częściowy i kompletny.
- [ ] Rozdzielić modele: rozmiar transferu, zajętość środowiska i przewidywany rozmiar artefaktu.
- [ ] Normalizować nazwę pakietu oddzielnie od specyfikacji wersji i extras; niewiadomą reprezentować jawnie, a nie jako `0 B`.
- [ ] Uwzględniać zależności przechodnie, zgodność wheel z docelową platformą/interpreterem i cache przy wyliczaniu transferu.
- [ ] Osobno uwzględniać pobranie uv, Pythona i narzędzi budowania. Pokazać zakres szacunku i brakujące informacje.
- [ ] Powiązać wynik preflight z wersją planu; odrzucać spóźnione wyniki i czyścić poprzedni stan po zmianie projektu.
- [ ] Zapewnić anulowanie preflight i czytelny powrót do przeglądu projektu po błędzie.

Akceptacja i testy: pierwsze uruchomienie bez cache działa przewidywalnie; brak sieci nie oznacza `0 B`; przypięty `pandas` dostaje oszacowanie lub jawny brak danych; pobranie części pakietów z cache zmniejsza transfer, a nie pozorny rozmiar EXE.

## A12. UI/UX od wyboru projektu do uruchomienia

Pliki: [`ui/screen_review.py`](../../../exelent/ui/screen_review.py), [`ui/screen_build.py`](../../../exelent/ui/screen_build.py), [`ui/app.py`](../../../exelent/ui/app.py), pozostałe komponenty `ui/` i katalogi `i18n/`.

- [ ] Przekazywać w wyniku osobno `artifact_dir` i `executable_path`; przycisk „Uruchom” ma działać dla ONEFILE i ONEDIR. Obecnie katalog ONEDIR nie spełnia warunku `is_file()`.
- [ ] Przed budowaniem pokazać zakres wejścia, wybrany entrypoint, zasoby, konwersje, zależności, tryb wyniku i pełną lokalizację docelową; umożliwić zmianę celu publikacji.
- [ ] Wyjaśnić, kiedy wynikiem jest pojedynczy EXE, a kiedy cały folder potrzebny do działania aplikacji. Pokazać powód automatycznej rekomendacji.
- [ ] Odróżnić blokery od ostrzeżeń przez treść i ikonę, nie tylko kolor; przy każdym problemie wskazać możliwe działanie.
- [ ] Udostępnić podgląd konwersji TXT oraz raport brakujących lub niepewnych zależności.
- [ ] Dodać przewijanie długiego podsumowania i sprawdzić układ przy małym oknie, skalowaniu Windows oraz długich ścieżkach.
- [ ] Udostępnić aktualizowany log w czasie budowania; fazy i komunikaty mają odpowiadać rzeczywistej pracy, także podczas pobierania i anulowania.
- [ ] Na ekranie wyniku zachować ostrzeżenia, pokazać EXE i katalog do udostępnienia, udostępnić otwarcie lokalizacji i raport.
- [ ] Zweryfikować obsługę klawiatury, kolejność fokusu, widoczność przycisków oraz kompletność PL/EN, również dla diagnostyki generowanej przez launcher.

Akceptacja: przejść ręcznie scenariusze pojedynczego PY, TXT z poprawkami, pakietu z zasobami, brakującej zależności, anulowania i ponownego builda. Każdy kończy się jasną informacją o wyniku i dalszej czynności. Automatyzować istotne zachowania, takie jak uruchamianie ONEDIR i widoczność ostrzeżeń; prostych zmian wizualnych nie pokrywać testami odtwarzającymi implementację.

## A13. Struktura rdzenia i izolacja sesji

Pliki: [`cli.py`](../../../exelent/cli.py), [`models.py`](../../../exelent/models.py), [`analysis/project.py`](../../../exelent/analysis/project.py), [`build/backend.py`](../../../exelent/build/backend.py), [`build/workspace.py`](../../../exelent/build/workspace.py), [`runtime/paths.py`](../../../exelent/runtime/paths.py).

- [ ] Pozostawić CLI jako adapter argumentów i prezentacji, a orkiestrację budowania przenieść do usługi rdzenia opisanej w A02.
- [ ] Faktycznie wykorzystać kontrakt backendu do wstrzykiwania implementacji i testowania orkiestracji.
- [ ] Współdzielić wynik parsowania AST między analizą entrypointu, rodzaju aplikacji i zależnościami, zamiast wielokrotnie parsować te same źródła.
- [ ] Zapewnić spójny, niemutowalny obraz analizy i planu; samo `frozen=True` nie zabezpiecza modyfikowalnych słowników wewnątrz modelu.
- [ ] Przekazywać docelową wersję Pythona z planu do środowiska, walidacji, resolvera i backendu; usunąć ignorowane lub dublowane źródła tej informacji.
- [ ] Dodać unikalny identyfikator sesji do workspace, logów i tymczasowej publikacji. Dwie instancje dla tego samego projektu nie mogą usuwać sobie katalogów.
- [ ] Wspólny cache narzędzi i środowisk zabezpieczyć przed równoległym zapisem; oddzielić go od danych sesji.
- [ ] Skrócić komentarze opisujące historię poprzednich napraw; pozostawić kontrakty i uzasadnienia, a szersze decyzje opisać w dokumentacji.

Akceptacja i testy: GUI i CLI korzystają z tej samej usługi; dwie sesje tego samego projektu są niezależne; zmiana targetu dociera do całego pipeline; test granic warstw nadal przechodzi.

## A14. Testy regresji i bramki jakości

- [ ] Izolować ustawienia użytkownika oraz `LOCALAPPDATA` w testach UI; poprawić test wyboru języka bez zmiany poprawnego pierwszeństwa zapisanej preferencji.
- [ ] Dla każdej naprawy P0/P1 najpierw dodać reprodukcję zachowania, następnie sprawdzić zmianę na publicznym kontrakcie.
- [ ] Rozszerzyć golden tests o rzeczywiste uruchomienie EXE i sprawdzenie rezultatu, a nie tylko istnienia pliku lub kodu wyjścia PyInstallera.
- [ ] Utrzymywać scenariusze: skrypt, pakiet, `src/`, lokalne importy, konwersja zagnieżdżonego TXT, zasoby, ONEFILE, ONEDIR, wymagane i opcjonalne zależności oraz ponowny build.
- [ ] Testować uruchomienie z obcego katalogu, ścieżki ze spacjami i znakami polskimi, kolizje nazw oraz błędy uprawnień i brak miejsca przez kontrolowane fixture'y.
- [ ] Przetestować pełny bootstrap docelowego Pythona 3.12 w środowisku bez przygotowanego cache oraz powtórny build z cache.
- [ ] Sprawdzić anulowanie i równoległe sesje niezależnie od pełnych buildów, wykorzystując kontrolowane procesy i synchronizację.
- [ ] Uruchomić właściwe testy modułów, następnie pełny zestaw bez `slow`, ruff i wymagane golden tests. Nie powtarzać kosztownych przebiegów bez zmiany lub nierozstrzygniętego problemu.
- [ ] Upewnić się, że CI dla zmian pipeline obejmuje powyższe scenariusze, a wydanie opiera się na sprawdzonym artefakcie i wyniku testów docelowej konfiguracji.

## Etapy dostarczenia

1. **Ochrona danych i kontrola zakresu:** A01, A02, izolacja sesji z A13 oraz odpowiadające im regresje.
2. **Poprawne źródła i struktura paczki:** A03–A06; uruchamiane EXE dla pakietów, zasobów i TXT.
3. **Kompletne środowisko i wiarygodny wynik:** A07, A08 oraz walidacja docelowym Pythonem.
4. **Odporność i informacja zwrotna:** A09–A11; responsywność, limity, anulowanie i preflight.
5. **Domknięcie UX i utrzymania:** A12, pozostałe A13, dokumentacja i kompletna macierz A14.

Każdy etap kończy się działającym przyrostem z odpowiednimi testami. Zmiany UI potrzebne do pokazania nowych błędów należy dostarczać razem z naprawą rdzenia, a nie odkładać do ostatniego etapu.

## Warunki zakończenia planu

- [ ] Wszystkie A01–A14 mają zrealizowane kryteria akceptacji lub jawnie opisane, uzasadnione ograniczenie obsługi danego rodzaju projektu.
- [ ] Kolejny build i awaria publikacji zachowują poprzedni artefakt oraz dane użytkownika.
- [ ] Build odpowiada zaakceptowanemu planowi; konwersja nie zmienia znaczenia poprawnego kodu.
- [ ] Kontrolowane aplikacje z pakietami, zasobami i zależnościami działają po spakowaniu w obu obsługiwanych trybach.
- [ ] Brak wymaganej zależności, niepoprawny kod i niekompletny artefakt nie kończą się komunikatem sukcesu.
- [ ] Anulowanie, błędy I/O i duże wejścia mają przewidywalną obsługę, a GUI pozostaje responsywne.
- [ ] Wyniki testów są niezależne od ustawień dewelopera; docelowy interpreter i pełny bootstrap zostały sprawdzone.
- [ ] README i komunikaty PL/EN odpowiadają rzeczywistemu zakresowi obsługi oraz formatowi wyniku.
