# EXElent — poprawki UI po pierwszych testach

**Data:** 2026-08-28
**Status:** zatwierdzony, gotowy do planu implementacji
**Poprzednik:** `2026-08-24-exelent-design.md` (dokument bazowy; ten go uzupełnia, nie zastępuje)

## 1. Cel

Pierwsze testy działającego programu dały siedem zgłoszeń dotyczących interfejsu.
Ten dokument opisuje ich rozwiązanie. Logika biznesowa (przypadki, w których build
się wykłada) jest świadomie odłożona na później — najpierw interfejs ma przestać
wprowadzać użytkownika w błąd.

Siedem zgłoszeń, skrótowo:

| # | Zgłoszenie | Sekcja |
|---|---|---|
| 1 | Przeciągnięcie pliku wybiera cały katalog nadrzędny | §4 |
| 2 | Nie da się cofnąć po wybraniu źródła — trzeba zresetować program | §5 |
| 3 | Brak realnego postępu pobierania: ile danych, jak szybko, jak długo | §8 |
| 4 | Brak okna z szacowanym rozmiarem pobierania przed startem | §9 |
| 5 | „Postać wyniku" schowana w opcjach zaawansowanych | §6 |
| 6 | Nie widać, co program zarekomendował, gdy użytkownik to zmieni | §6 |
| 7 | Ostrzeżenie „kilkaset MB" przy realnym wyniku ~26 MB | §7 |

Kryterium sukcesu: na tym samym skrypcie testowym, na którym powstały zgłoszenia,
użytkownik widzi przed buildem prawdziwą liczbę megabajtów do pobrania, w trakcie
— prędkość i pozostały czas, a po — rozmiar mieszczący się w podanych wcześniej
widełkach.

## 2. Decyzje fundamentalne

| Decyzja | Wybór | Uzasadnienie |
|---|---|---|
| Upuszczony pojedynczy plik | **projektem jest ten plik** plus importowane moduły lokalne | gdyby użytkownik chciał cały katalog, przeciągnąłby katalog |
| Głębokość postępu pobierania | **MB, prędkość i pozostały czas** | wolne łącze to główny przypadek bólu; sam ułamek nie mówi nic |
| Źródło rozmiaru pobierania | **`uv pip install --dry-run` + PyPI JSON API** | daje liczbę dokładną dla konkretnych wersji, nie zgadywaną |
| Źródło szacunku rozmiaru EXE | **wbudowana tabela zmierzonych wkładów**, podawana jako widełki | PyInstaller wycina nieużywane moduły, więc rozmiar koła to zła miara |
| Oznaczanie rekomendacji | **dopisek „(zalecane)" + link „przywróć zalecane"** | odpowiada na oba pytania: co było zalecane i jak do tego wrócić |
| Magazyn ustawień | **`settings.json` w `state_dir()`**, rdzeń bez Qt | ta sama warstwa i ten sam styl obronny co `recent.py` |
| Protokół postępu | **obiekt `Progress`** zamiast pary `(faza, ułamek)` | bajtów, prędkości i ETA nie da się przemycić przez `float` |

### Warianty odrzucone

- **Upuszczony plik jako preselekcja pliku głównego w katalogu nadrzędnym** —
  najmniejsza zmiana, ale nie rozwiązuje problemu: przy `test.txt` w Pobranych
  nadal skanujemy i kopiujemy setki obcych plików (patrz §4, akapit o kopii
  roboczej).
- **Pytanie przy każdym upuszczeniu pliku („ten plik czy cały folder?")** —
  bezpieczne, ale dokłada klik do najczęstszego odruchu użytkownika i przenosi
  na niego decyzję, którą program potrafi podjąć sam.
- **Sumowanie rozmiaru pobierania z linii `Downloading` uv** — zmierzone jako
  błędne: uv nie drukuje tych linii dla małych paczek (§8.3), więc suma
  byłaby systematycznie zaniżona.
- **PyPI jako źródło szacunku rozmiaru EXE** — rozmiar koła to rozmiar
  *pobierania*. PyInstaller wyrzuca z paczki to, czego kod nie dotyka, i to
  jest dokładna przyczyna zgłoszenia 7.
- **Kalibracja szacunku na podstawie własnych udanych buildów użytkownika** —
  kusząca i tania, ale to nowy stan trwały i nowa klasa błędów („skąd on wziął
  tę liczbę"). Poza zakresem, patrz §13.
- **Utrzymanie `ProgressFn` jako `(faza, ułamek)` z opcjonalnymi parametrami** —
  sygnatura z pięcioma opcjonalnymi argumentami, których nikt nie umie
  wypełnić w połowie. Jeden obiekt jest uczciwszy.

## 3. Zakres zmian w architekturze

Zasada naczelna dokumentu bazowego zostaje bez zmian: **rdzeń nie importuje Qt**,
zależności idą wyłącznie `ui` → rdzeń. Pilnuje tego `tests/test_layering.py` i
każdy nowy moduł rdzenia musi przez ten test przejść.

Moduły nowe:

| Moduł | Warstwa | Odpowiedzialność |
|---|---|---|
| `exelent/settings.py` | rdzeń | trwałe ustawienia użytkownika (`settings.json`) |
| `exelent/runtime/progress.py` | rdzeń | struktura `Progress` — jedyny kształt postępu |
| `exelent/runtime/uvlog.py` | rdzeń | parser linii zdarzeń uv → zdarzenia typowane |
| `exelent/deps/sizes.py` | rdzeń | rozwiązanie zależności, rozmiary z PyPI, tabela wkładów do EXE |
| `exelent/ui/dialog_download.py` | ui | okno przed pobieraniem |
| `exelent/ui/dialog_settings.py` | ui | ustawienia (koło zębate) |
| `exelent/ui/preflight.py` | ui | wątek liczący rozmiary dla ekranu 2 |

Moduły zmienione: `analysis/scanner.py`, `analysis/project.py`, `models.py`,
`planning.py`, `build/workspace.py`, `runtime/paths.py`, `runtime/bootstrap.py`,
`runtime/env.py`, `build/pyinstaller.py`, `cli.py`, `ui/app.py`, `ui/rows.py`,
`ui/recent.py`, `ui/screen_drop.py`, `ui/screen_review.py`, `ui/screen_build.py`,
`ui/worker.py`, `i18n/pl.py`, `i18n/en.py`.

## 4. Tryb jednoplikowy (zgłoszenie 1)

### Problem, głębszy niż wygląda

`DropScreen._folder_from` robi dziś `path if path.is_dir() else path.parent`.
Upuszczony `test.txt` z Pobranych daje więc `root = ~/Downloads`. Konsekwencje
sięgają dalej niż ekran 2:

- `scan_directory` skanuje całe Pobrane (limit `MAX_SCAN_FILES` = 3000 tłumi
  objaw, ale nie usuwa przyczyny),
- `materialize_workspace` robi `copytree(plan.root)` — czyli **kopiuje całe
  Pobrane do `%LOCALAPPDATA%`**,
- `default_dest_dir` szuka miejsca na wynik względem Pobranych,
- analiza zależności czyta importy z każdego obcego skryptu w tym katalogu.

Naprawa samego ekranu 1 zostawiłaby trzy ostatnie punkty nietknięte.

### Rozwiązanie

`ScanResult` i `ProjectAnalysis` dostają pole `single_file: Path | None`.
Niepuste znaczy: użytkownik wskazał plik, nie katalog.

`exelent/analysis/scanner.py` dostaje `scan_single_file(path) -> ScanResult`:

- `root = path.parent` (potrzebne, bo ścieżki względne w kodzie użytkownika i
  `work_dir_for` nadal potrzebują punktu odniesienia),
- `single_file = path`,
- `py_files` albo `text_candidates` zawiera **wyłącznie** ten plik (o
  przynależności decyduje ta sama logika co dziś: sufiks `.py`/`.pyw`, a dla
  `.txt` — `looks_like_python`),
- `data_files`, `icon_files`, `requirements` — puste. Katalog nadrzędny nie
  jest projektem, więc leżące w nim `requirements.txt` czy `icon.png` nie mają
  z tym plikiem nic wspólnego.

### Moduły lokalne

Skrypt importujący sąsiedni `helper.py` musi działać, inaczej tryb jednoplikowy
psuje przypadki, które dziś działają. Po wstępnej analizie importów zbieramy
tranzytywne domknięcie modułów lokalnych rozwiązywalnych względem `root`
(plik `nazwa.py` albo katalog `nazwa/__init__.py`), z twardym limitem
zapobiegającym wciągnięciu połowy katalogu: **maks. 50 plików**; po jego
przekroczeniu zostaje sam plik wskazany, a użytkownik dostaje ostrzeżenie.

Dociągnięte pliki są **widoczne na ekranie 2** jako wiersz „Dołączam też:
helper.py, util.py". Ciche wciąganie plików jest tym samym błędem, co ciche
wciąganie katalogu — tylko mniejszym.

### Kopia robocza i katalog roboczy

`materialize_workspace` przy `single_file` kopiuje **wyliczony zbiór plików**
zamiast `copytree`. Struktura katalogów względem `root` jest zachowana, żeby
importy pakietowe nadal się rozwiązywały.

`work_dir_for` przy `single_file` hashuje **ścieżkę pliku**, nie katalogu. Bez
tego `a.py` i `b.py` z Pobranych dzielą jeden katalog roboczy i drugi build
kasuje środowisko pierwszego — a `path_hash` jest jedyną rzeczą, która te
przebiegi rozdziela.

### Ekran 1

`_folder_from` zostaje zastąpiony przez `_source_from(mime) -> Path | None`,
który oddaje ścieżkę **bez zamiany pliku na katalog**. Rozróżnienie
plik/katalog przenosi się do `analyze_project`, które wybiera `scan_directory`
albo `scan_single_file`. Odrzucanie tego, co nie jest ścieżką lokalną
(link z przeglądarki, zaznaczony tekst), zostaje bez zmian — to nadal jedyna
obrona przed analizą przypadkowego katalogu.

Lista „Ostatnie" musi przyjąć pliki: `recent.load_recent` filtruje dziś przez
`path.is_dir()`, co po tej zmianie cicho gubiłoby każdy wpis jednoplikowy.
Warunek zmienia się na `path.exists()`.

## 5. Nawigacja wstecz (zgłoszenie 2)

`ReviewScreen` dostaje sygnał `back_requested` i przycisk „← Wstecz". `MainWindow`
podpina go pod powrót na ekran 1 wraz z `refresh_recent()`.

`BuildScreen` w stanach **nie udało się** i **przerwane** dostaje przycisk
„← Wróć do ustawień" → sygnał `back_to_review`, który wraca na ekran 2 **z
zachowaną analizą**. Poprawienie nazwy po nieudanym buildzie nie może kosztować
ponownego skanu katalogu. `MainWindow` trzyma w tym celu ostatnią
`ProjectAnalysis`; ekran 2 i tak jest długożyjącym widgetem, więc wystarczy go
nie czyścić.

Przycisk nie pojawia się w stanie **udało się** — tam właściwą akcją jest
„Zrób następny program", która już istnieje.

`MainWindow` blokuje każde cofnięcie, gdy `worker.is_running()`. Bez tego
użytkownik wraca na ekran 1, wybiera inny folder i startuje drugi build; oba
korzystają z tego samego cache'u środowisk, co dokument bazowy wyklucza.
`BuildWorker.start` odrzuca dziś taki drugi build po cichu — użytkownik
zobaczyłby ekran postępu, który nigdy nie ruszy.

## 6. Ekran 2: postać wyniku i rekomendacje (zgłoszenia 5, 6)

### Postać wyniku wychodzi z ukrycia

`mode_combo` przenosi się z panelu „Zaawansowane" do głównej karty jako piąty
`FactRow`, na równi z plikiem głównym i rodzajem programu. To informacja o tym,
co użytkownik dostanie na końcu — jeden plik czy folder — więc domyślne ukrycie
było błędem.

Po przeniesieniu panel „Zaawansowane" jest pusty, więc **znika razem z
przełącznikiem** (`advanced`, `advanced_toggle`, `_show_advanced`,
`_toggle_advanced`, stałe `COLLAPSED`/`EXPANDED`, klucz `review_advanced`).
Panel z jedną opcją, która właśnie z niego wyszła, byłby pustym miejscem
czekającym na wypełnienie „czymkolwiek" — a najlepszym kandydatem (katalog
docelowy) świadomie się teraz nie zajmujemy (§13).

### Rekomendacje

`FactRow` dostaje `set_recommended(value: str)` oraz stan „zmienione przez
użytkownika", wyliczany z porównania bieżącej wartości z zapamiętaną
rekomendacją. Wiersz zyskuje trzeci element: link „przywróć zalecane",
**widoczny wyłącznie wtedy, gdy bieżąca wartość różni się od rekomendowanej**.

Pozycja rekomendowana na liście rozwijanej dostaje dopisek „(zalecane)".
Dopisek jest **wyłącznie etykietą** — `currentData()` nadal oddaje czyste
`AppKind`/`OutputMode`/`Path`. To nie jest drobiazg: `_emit_plan` już raz
przewrócił się na tym, że Qt oddaje dane pozycji jako goły napis (patrz komentarz
przy `AppKind(self.kind_combo.currentData())`), i wtedy użytkownik dostawał
czarną konsolę za każdym GUI.

Zakres: **plik główny, rodzaj programu, postać wyniku** — dokładnie te trzy,
o które prosiło zgłoszenie 6. Nazwa i ikona używają tego samego mechanizmu
`FactRow` i można je włączyć jedną linijką każde, gdyby okazało się to potrzebne.

Rekomendacja jest ustalana raz, w `load()`, z `ProjectAnalysis` — nie
przeliczana po każdej zmianie użytkownika. Rekomendacja, która goni wybór
użytkownika, nie jest rekomendacją.

Znacznik pewności `✓`/`?` zostaje niezmieniony i **niezależny** od rekomendacji:
mówi, czy analiza była pewna, a nie czy użytkownik coś zmienił. Mieszanie tych
dwóch znaczeń w jednym symbolu było wariantem odrzuconym.

## 7. Rozmiar: dwie różne liczby (zgłoszenie 7)

### Przyczyna zgłoszenia

`Dependency.heavy` to flaga boolowska ustawiana przez przynależność do
`HEAVY_PACKAGES` — zbioru 12 nazw. `analyze_project` zamienia jej wystąpienie na
`Issue("heavy_packages", ...)`, a `i18n` na stałe zdanie „Plik EXE może mieć
kilkaset megabajtów". **Nigdzie w tej ścieżce nie ma żadnej arytmetyki.**
Skrypt z matplotlib, pandas i scipy dostaje to samo zdanie co skrypt z torch,
i stąd „kilkaset MB" przy realnym wyniku ~26 MB.

Drugim źródłem błędu jest mieszanie dwóch różnych wielkości. Rozdzielamy je.

### 7.1 Rozmiar pobierania — dokładny

`uv pip install --dry-run` oddaje pełne rozwiązane drzewo z przypiętymi
wersjami oraz liczbę paczek, których naprawdę brakuje w cache. Zmierzone
wyjście (stderr, dla `matplotlib pandas scipy`, uv 0.8.17):

```
Using Python 3.12.11 environment at: probe-venv
Resolved 14 packages in 18ms
Would download 8 packages
Would install 14 packages
 + contourpy==1.3.3
 + matplotlib==3.11.1
 ...
```

Dla każdej pozycji `nazwa==wersja` z tego zbioru pytamy PyPI JSON API
(`https://pypi.org/pypi/{nazwa}/{wersja}/json`) o rozmiar koła. Wybór koła:
`bdist_wheel` pasujące do `cp312` i `win_amd64`, w razie braku — `py3-none-any`,
w ostateczności `sdist`. Zmierzone wyniki: `scipy 1.18.1` → 35,0 MB,
`numpy 2.5.2` → 11,9 MB, `matplotlib 3.11.1` → 8,9 MB.

Zapytania idą równolegle (pula wątków), z krótkim limitem czasu. **Każda
porażka jest cicha** i degraduje do szacunku z tabeli §7.2 — rozmiar
pobierania jest wygodą, a nie powodem, dla którego build ma nie ruszyć.
To ta sama zasada, która rządzi `recent.py`.

Suma dotyczy **wyłącznie** zbioru „would download". Drugi build tego samego
projektu uczciwie mówi „nic do pobrania", zamiast straszyć liczbą, która już
leży w cache.

### 7.2 Rozmiar EXE — widełki z tabeli

`exelent/deps/sizes.py` zawiera `EXE_CONTRIBUTION: dict[str, tuple[int, int]]`
— zmierzony dolny i górny wkład paczki do gotowego EXE, w MB. Widełki, a nie
jedna liczba, bo rozpiętość jest realna: PyInstaller wyrzuca to, czego kod nie
dotyka, więc ten sam `pandas` waży inaczej w skrypcie czytającym jeden CSV, a
inaczej w programie używającym połowy API.

`HEAVY_PACKAGES` (płaski `frozenset`) **znika**, zastąpiony kluczami tej tabeli.
Flaga `Dependency.heavy` zostaje, ale jest wyliczana jako „paczka jest w tabeli
i jej górny wkład przekracza próg".

`Issue("heavy_packages", ...)` zostaje zastąpione przez
`Issue("size_estimate", Severity.INFO, {"low", "high", "packages"})`:

> „Gotowy program zajmie około 25–40 MB. Najwięcej miejsca zajmą: scipy, pandas."

Severity spada z `WARNING` na `INFO`: 26 MB nie jest problemem, o którym trzeba
ostrzegać, tylko informacją. `WARNING` zostaje wyłącznie powyżej progu, przy
którym rozmiar naprawdę jest problemem (górne widełki ≥ 300 MB) — wtedy tekst
mówi też o dłuższym czasie budowania.

Uwaga wdrożeniowa: ekran 2 pokazuje dziś w `warnings_label` wyłącznie Issue o
severity **innym niż INFO**, a `cli.run_build` przenosi dalej te, które nie są
BLOCKERem. Zejście na INFO wymaga więc świadomej zmiany w obu tych miejscach,
inaczej nowy komunikat o rozmiarze zniknie z ekranu zamiast zastąpić stary.

Gdy żadna zależność nie jest w tabeli, `Issue` nie powstaje wcale. Dziś jego
brak też oznacza „nic ciężkiego", więc zachowanie jest spójne.

### 7.3 Tabela musi zostać zmierzona

**Wartości w `EXE_CONTRIBUTION` mają pochodzić z prawdziwych buildów, nie z
oszacowania.** Plan implementacji zawiera osobne zadanie: zbudować minimalne
skrypty-świadki dla każdej paczki z tabeli (import + jedno realne użycie),
zmierzyć rozmiar EXE, odjąć rozmiar bazowy pustego skryptu i zapisać wynik.
Do czasu wykonania tego zadania wpisy są oznaczone w kodzie jako **tymczasowe**,
a test pilnuje, że każdy klucz tabeli ma odnotowaną datę pomiaru.

Zgłoszenie 7 mówi dokładnie o tym, że liczby wzięte z sufitu wprowadzają w
błąd. Zastąpienie jednego sufitu drugim nie byłoby naprawą.

## 8. Protokół postępu i parser uv (zgłoszenie 3)

### 8.1 Zmiana interfejsu

`ProgressFn = Callable[[str, float], None]` zastępuje:

```python
@dataclass(frozen=True)
class Progress:
    phase: str
    fraction: float          # 0.0-1.0, nigdy nie maleje
    done_bytes: int = 0
    total_bytes: int = 0
    speed_bps: float = 0.0
    eta_s: float | None = None

ProgressFn = Callable[[Progress], None]
```

Zmiana przechodzi przez `runtime/bootstrap.py`, `runtime/env.py`,
`build/pyinstaller.py`, `cli._Progress`, `ui/worker.py` i `ui/screen_build.py`.
`BuildWorker.progress` zmienia sygnaturę z `Signal(str, float)` na
`Signal(object)`.

Pola bajtowe są zerowe dla faz, które nic nie pobierają (pakowanie
PyInstallerem). Ekran 3 pokazuje drugą linijkę **tylko wtedy, gdy
`total_bytes > 0`** — pusty licznik bajtów pod paskiem przy pakowaniu byłby
gorszy niż jego brak.

`_Progress` z `cli.py` zachowuje obie swoje własności: sklejanie dwóch
niezależnych skal w jedną i monotoniczność (`_highest`). Obie są opisane w
komentarzach jako wynik obserwacji na żywym buildzie i żadna nie może zginąć
przy przepisywaniu.

**Ta zmiana rozbija inwentarz i18n i musi go naprawić w tym samym kroku.**
`tests/i18n/inventory.py` skanuje AST rdzenia w poszukiwaniu wywołań
`progress("faza", ...)` i bierze fazę z **pierwszego argumentu, o ile jest
literałem**. Po przejściu na obiekt faza siedzi w `Progress(phase="...")`, więc
skaner przestaje ją widzieć — i wszystkie fazy postępu wypadają z inwentarza
**po cichu**, czyli dokładnie tak, jak opisuje to docstring tego pliku
(„lista przepisana ręcznie starzeje się po cichu; nikt nie dostaje czerwonego
testu, tylko użytkownik dostaje goły kod zamiast zdania").

Inwentarz musi więc nauczyć się nowego kształtu: rozpoznawać `Progress(...)`
z literalnym `phase=` i nadal wymagać deklaracji dla miejsc dynamicznych
(`DECLARED_DYNAMIC_PHASES` wskazuje dziś `build/pyinstaller.py::build`, które
przepisuje wartości z `PHASES`). Test `test_every_progress_phase_is_translated`
ma po tej zmianie nadal świecić na czerwono, gdy nowa faza nie ma zdania —
zweryfikowane celowym usunięciem klucza, a nie założone.

### 8.2 Parser wyjścia uv

`create_build_env` używa dziś `subprocess.run(capture_output=True)`, który
buforuje całe wyjście do zakończenia procesu — **na żywo nie ma czego
pokazywać**. Zastępuje go `Popen` ze strumieniowym czytaniem stderr linia po
linii, przy zachowaniu pełnego tekstu dla `explain_log` w razie porażki.
`creationflags=CREATE_NO_WINDOW` zostaje — okno konsoli mignięte użytkownikowi
GUI jest tym, przed czym ta flaga broni.

Do wywołań uv dochodzi `--color never` jako tania polisa: zmierzone wyjście na
potoku nie zawierało sekwencji ANSI, ale regex, który się o nie przewróci,
zepsuje pasek postępu w sposób trudny do zauważenia.

`exelent/runtime/uvlog.py` rozpoznaje formaty **zmierzone na uv 0.8.17**:

| Linia | Znaczenie |
|---|---|
| `Downloading pillow (6.9MiB)` | start pobierania, z rozmiarem |
| `  Downloading pillow` (wiodąca spacja, bez rozmiaru) | koniec pobierania |
| `Resolved 14 packages in 18ms` | rozwiązano zależności |
| `Would download 8 packages` | (tylko `--dry-run`) ile brakuje w cache |
| `Prepared 1 package in 1.25s` | **wszystkie** pobierania zakończone |
| `Installed 2 packages in 18ms` | instalacja zakończona |
| ` + pillow==12.3.0` | konkretna paczka w wyniku |

Liczba mnoga bywa pojedyncza (`1 package` obok `2 packages`), więc wzorce muszą
przyjmować obie formy. Linia nierozpoznana zwraca `None`. Parser nigdy nie
rzuca — postęp jest ozdobą, a nie powodem, dla którego build ma paść.

### 8.3 Dwie pułapki, obie zmierzone

**uv nie drukuje linii `Downloading` dla małych paczek.** `six` i `packaging`
zainstalowane z `--no-cache --reinstall` nie wyprodukowały ani jednej takiej
linii. Parser sumujący te linie zaniżałby całość systematycznie i pasek nigdy
nie doszedłby do 100%. Dlatego:

- **suma** pochodzi z PyPI (§7.1), nie z linii uv,
- `Prepared N packages` jest twardym sygnałem 100% dla fazy pobierania.

Linie `Downloading` z ich rozmiarami służą wyłącznie za **zapasowe** źródło
sumy, gdy PyPI było nieosiągalne.

**`uv python install` używa tego samego formatu, ale nazwa zawiera nawiasy:**

```
Downloading cpython-3.11.13-windows-x86_64-none (download) (24.3MiB)
 Downloading cpython-3.11.13-windows-x86_64-none (download)
```

Naiwny regex bierze pierwszy nawias i wywraca się na `(download)`. Wzorzec musi
być zakotwiczony na **ostatnim** nawiasie linii i wymagać w nim jednostki
rozmiaru. Efekt uboczny jest korzystny: pobranie interpretera (24 MB — na wolnym
łączu w pełni odczuwalne, a dziś całkowicie nieme) obsługuje ten sam kod.

Jednostki występują jako `KiB`/`MiB`/`GiB` (potęgi 1024) — parser przelicza je
na bajty i nie miesza z `KB`/`MB` warstwy prezentacji.

### 8.4 Prędkość, ETA i interpolacja

Prędkość liczona jako **średnia wykładnicza** (EWMA) z przyrostów bajtów w
czasie, żeby zerwane łącze było widać jako spadek, a nie jako stałą sprzed
minuty. ETA = `pozostałe_bajty / prędkość`, pomijane przy prędkości bliskiej zeru.

Ponieważ uv raportuje **zakończenie** pobrania, licznik rośnie skokowo. Przy
paczce takiej jak `torch` (~800 MB) to jeden skok i pasek stojący kilkanaście
minut — czyli dokładnie zgłoszenie 3. Dlatego w obrębie pobieranej paczki
licznik jest **interpolowany** po zaobserwowanej prędkości, z twardym
przycięciem na **95% rozmiaru tej paczki**.

To jest świadome zgadywanie. Przycięcie istnieje po to, żeby pasek nigdy nie
utknął na 100% w oczekiwaniu na zdarzenie zakończenia — pasek, który dotarł do
końca i stoi, kłamie bardziej niż pasek, który stoi w 95%.

uv pobiera równolegle, więc kilka paczek bywa „w locie" naraz. Księgowanie
trzyma zbiór trwających pobrań, a nie pojedyncze bieżące — inaczej druga
równoległa paczka kasowałaby postęp pierwszej.

## 9. Ustawienia i okno przed pobieraniem (zgłoszenie 4)

### 9.1 Magazyn

`exelent/settings.py` — rdzeń, bez Qt, `settings.json` w `state_dir()`:

```json
{ "ask_before_download": true, "language": null }
```

Styl obronny skopiowany z `recent.py`, bo powody są te same: uszkodzony lub
niedostępny plik oddaje **wartości domyślne**, a nieudany zapis nie przerywa
pracy. Ustawienia są wygodą i nie mogą być powodem, dla którego program nie
rusza. Nieznany klucz w pliku jest ignorowany, brakujący — uzupełniany domyślną
wartością.

`language: null` znaczy „idź za językiem systemu" (`system_language()`), czyli
zachowuje dzisiejsze zachowanie dla każdego, kto niczego nie wybrał.

### 9.2 Okno przed pobieraniem

Pojawia się po kliknięciu „Stwórz EXE", **wyłącznie gdy** jest co pobierać
(`would_download > 0`) **i** `ask_before_download` jest włączone.

Treść: liczba paczek, łączny rozmiar, lista największych pozycji. Checkbox
„Nie pytaj ponownie" zapisuje `ask_before_download = false`. Przyciski:
„Pobierz i buduj" / „Anuluj" (powrót na ekran 2, bez startowania builda).

Okno nie pojawia się, gdy wszystko jest w cache — pytanie o zgodę na pobranie
zera megabajtów uczy użytkownika klikać „OK" bez czytania.

Gdy preflight (§9.4) jeszcze nie skończył, okno czeka na jego wynik z krótkim
limitem czasu, po którym pokazuje szacunek z tabeli. Kliknięcie „Stwórz EXE"
nie może zawiesić okna na zapytaniu sieciowym.

### 9.3 Ustawienia z ekranu 1

Przycisk z kołem zębatym w rogu ekranu 1 otwiera `dialog_settings`:
przełącznik „Pytaj przed pobieraniem zależności" oraz **wybór języka**.

Język trafia tam, bo `MainWindow.set_language` i sygnał `language_changed`
istnieją w kodzie i **nie mają dziś żadnego UI** — jedyną drogą do angielskiej
wersji jest zmiana języka systemu. Wybór zapisuje się do `settings.json` i jest
czytany przy starcie, przed konstrukcją ekranów; kolejność jest krytyczna i
opisana komentarzem w `MainWindow.__init__` (ekrany biorą napisy z `t()` w
konstruktorze).

Zmiana języka w działającym oknie wymaga przebudowania napisów już zbudowanych
ekranów. Sygnał `language_changed` istnieje, ale **nikt go dziś nie słucha** —
każdy ekran musi dostać metodę odświeżającą swoje etykiety i podpiąć się pod ten
sygnał. Bez tego przełącznik zadziała dopiero po restarcie programu, co jest
dokładnie tą klasą niespodzianki, którą ten dokument usuwa.

### 9.4 Preflight na ekranie 2

Rozwiązanie zależności (`--dry-run`) i odpytanie PyPI wymagają uv i sieci, więc
nie mogą blokować wątku okna. `ui/preflight.py` robi to w `QThread` startowanym
przy wejściu na ekran 2, **tylko gdy są zależności**.

Ekran 2 pokazuje w międzyczasie „Potrzebne dodatki — sprawdzam rozmiar…", a po
zakończeniu „…razem około 96 MB do pobrania". Wątek jest anulowalny (wyjście
z ekranu 2 go zatrzymuje) i **cicho degraduje**: brak uv, brak sieci lub błąd
PyPI zostawia dzisiejszy tekst i szacunek z tabeli §7.2.

Świadomy koszt: ekran 2 zaczyna dotykać sieci przy wejściu, czego dziś nie
robi. Jest to ograniczone do przypadku z zależnościami, wykonywane w tle i
nigdy nie blokujące budowania.

Przy pierwszym uruchomieniu uv może jeszcze nie być na dysku. Preflight
**nie pobiera go** — to jest praca fazy budowania, z własnym paskiem postępu.
Bez uv preflight po prostu odpada do szacunku offline.

Wątek preflight jest niezależny od `BuildWorker` i musi być zatrzymany w
`MainWindow.closeEvent` na tej samej zasadzie co on: `QThread` zniszczony przez
Qt przy wychodzeniu to abort procesu.

## 10. Nowe i zmienione komunikaty

Nowe klucze (oba katalogi, `pl` i `en` — test kompletności liczy klucze z kodu
i zapala się na brakującym):

| Klucz | Rola |
|---|---|
| `size_estimate` | „Gotowy program zajmie około {low}–{high} MB. Najwięcej: {packages}." |
| `size_estimate_large` | wariant powyżej progu, z uwagą o czasie budowania |
| `single_file_extra` | „Dołączam też: {files}" |
| `single_file_too_many` | limit modułów lokalnych przekroczony |
| `download_size` | „{count} paczek — około {size} do pobrania" |
| `download_nothing` | „Wszystko już pobrane — budowanie ruszy od razu" |
| `download_checking` | „sprawdzam rozmiar…" |
| `progress_bytes` | „{done} z {total} · {speed}/s · zostało {eta}" |
| `dialog_download_title` / `_ok` / `_cancel` / `_dont_ask` | okno z §9.2 |
| `settings_title` / `_ask_download` / `_language` | okno z §9.3 |
| `review_back`, `build_back_to_review`, `review_restore` | §5, §6 |

Klucze usuwane: `heavy_packages` (zastąpiony przez `size_estimate`),
`review_advanced` (panel znika).

Formatowanie rozmiarów i czasu żyje **w jednym miejscu**. `_human_size` jest
dziś prywatne w `screen_build.py`; przenosi się do warstwy prezentacji jako
funkcja dzielona przez ekran 2, ekran 3 i oba okna dialogowe. Cztery niezależne
formatowania megabajtów rozjadą się co do zaokrąglenia.

## 11. Strategia testów

Rdzeń jest testowany bez okna i bez sieci — to zasada dokumentu bazowego i tu
się nie zmienia.

| Obszar | Testy |
|---|---|
| Parser uv | nagrane **prawdziwe** linie z sondy, łącznie z `(download)` w nazwie, milczeniem przy małych paczkach, liczbą pojedynczą `1 package` i linią zakończenia z wiodącą spacją; linia nierozpoznana → `None`, nigdy wyjątek |
| Rozmiary | parsowanie nagranego JSON-a z PyPI (wybór koła cp312/win_amd64, ścieżki zapasowe); **żadnej sieci w testach** |
| Postęp | monotoniczność `fraction`, sklejenie dwóch skal, interpolacja przycięta na 95%, `Prepared` wymuszające 100%, EWMA opadająca przy zerwaniu, dwie paczki pobierane równolegle |
| Tryb jednoplikowy | zakres analizy, domknięcie modułów lokalnych i jego limit, kopia robocza kopiująca **tylko** zbiór, `work_dir_for` rozróżniające dwa pliki w jednym katalogu, wariant `.txt` |
| Ustawienia | domyślne przy braku pliku, przy pliku uszkodzonym i przy odmowie zapisu |
| Ekran 2 | „(zalecane)" w etykiecie **przy nietkniętym `currentData()`**, link pojawiający się i znikający, wiersz postaci wyniku widoczny bez żadnego klikania, `size_estimate` (INFO) faktycznie widoczny |
| Nawigacja | cofnięcie zachowuje analizę; cofnięcie zablokowane w trakcie builda |
| Warstwy | `test_layering` — każdy nowy moduł rdzenia bez Qt |
| Inwentarz i18n | skaner widzi fazy w `Progress(phase=...)`; nowy kod Issue i nowa faza bez zdania nadal zapalają test — sprawdzone celowym usunięciem klucza |

Test jednoplikowy musi objąć wariant `.txt`, bo to ścieżka flagowa produktu
i dokładnie ten przypadek z oryginalnego zgłoszenia.

## 12. Kolejność wdrożenia

1. **§5 nawigacja** i **§6 ekran 2** — samodzielne, natychmiast widoczne, bez
   zależności od reszty.
2. **§4 tryb jednoplikowy** — dotyka rdzenia, ale nie zależy od §7–§9.
3. **§7 rozmiary** (z zadaniem pomiarowym §7.3).
4. **§8 protokół postępu i parser** — najszersza zmiana interfejsu.
5. **§9 ustawienia i okna** — stoi na §7 i §8, więc idzie na końcu.

## 13. Poza zakresem

Świadomie **nie** robimy teraz:

- **logiki biznesowej** — scenariusze, w których build się wykłada, są odłożone
  na osobną turę, zgodnie z decyzją zgłaszającego;
- **wyboru katalogu docelowego w UI** — najlepszy kandydat na odrodzony panel
  „Zaawansowane", ale poza siedmioma zgłoszeniami;
- **kalibracji szacunku rozmiaru** na podstawie udanych buildów użytkownika;
- **postępu bajtowego dla PyInstallera** — on nie pobiera, tylko pakuje; jego
  fazy zostają tekstowe;
- **przeniesienia `ui/recent.py` do rdzenia** obok `settings.py`, gdzie
  logicznie należy — refaktor niezwiązany z tymi zgłoszeniami.
