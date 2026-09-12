# EXElent — zaktualizowany plan niezawodności EXE, analizy i UX

Data: 2026-09-07. Stan odniesienia: `feat/ui-poprawki`, commit `70ce672`.

Status: **w realizacji — kontynuacja B15 po B14, przegląd 2026-09-12**. Historia zawiera implementacje mechanizmów B01–B14, ale nie potwierdza odbioru wszystkich ich kryteriów. Szczegółowy punkt wznowienia i wyniki są w sekcji 9. Puste pola pozostają wymaganiami do odbioru; sam tytuł commita nie wystarcza do ich zaznaczenia. Dokument zastępuje [plan z 2026-09-06](2026-09-06-plan-poprawy-exelent.md) jako bieżąca lista prac; poprzedni dokument pozostaje zapisem historii. Nowe identyfikatory B01–B15 pozwalają odróżnić aktualne zadania od dawnych deklaracji wykonania A01–A14.

## 1. Cel i granice

EXElent ma przekształcać wskazany projekt Python lub kod w TXT w aplikację Windows, którą osoba bez wiedzy programistycznej potrafi zbudować, uruchomić i przekazać dalej.

Priorytetem jest zgodność gotowego programu z wejściem i wyborami użytkownika: zachowanie treści kodu, kompletność importów i zasobów, spójność środowiska oraz trwałość zapisanych danych. Kod wyjścia 0 PyInstallera oznacza zakończenie pakowania, a nie dowód poprawnego działania aplikacji.

Zakres obejmuje cały przepływ:

`wejście → dekodowanie/konwersja → analiza → zaakceptowany plan → kopia źródeł → środowisko → walidacja → PyInstaller/launcher → publikacja → wynik GUI/CLI`.

Nie zakłada się przepisywania projektu ani dodawania drugiego backendu. Zachowujemy istniejący podział na `analysis`, `planning`, `runtime`, `build`, `diagnostics` i `ui`. Zmiany mają ujednolicić kontrakty między tymi warstwami.

## 2. Dowody i ograniczenia przeglądu

Poniższe wyniki pochodzą z przeglądu w tej sesji, poprzedzającego utworzenie dokumentu. Nie są nowym uruchomieniem testów podczas pisania planu.

- `pytest -m "not slow" -q`: **788 zaliczonych, 21 odznaczonych**.
- `ruff check .`: bez błędów. Nie wykonywano wtedy `ruff format --check .`.
- Trzy kontrolowane buildy używały lokalnego Pythona **3.13.5** i PyInstallera **6.16.0**, przez `execute_build` z podstawionym gotowym środowiskiem i pominiętym sprawdzaniem sieci. Źródła testowe były utworzone na potrzeby audytu.
- Nie wykonano pełnego zestawu golden, pełnego bootstrapu Pythona 3.12 ani nowego wydania EXElent.exe.
- Ocena UI opiera się na kodzie, istniejących testach oraz kontrolowanych próbach komponentów. Nie zastępuje ręcznej oceny na Windows przy różnych skalowaniach i rozdzielczościach.
- Reprodukcje audytowe nie zostały jeszcze dodane do repozytorium jako testy regresji. Ich utrwalenie jest częścią zadań poniżej.

| Przypadek | Dowód z przeglądu | Wniosek |
|---|---|---|
| Alias `open` zapisujący plik | Rzeczywisty EXE: plik istniał w `_MEI...`, po zakończeniu programu już nie | Utrata danych przez błędny ONEFILE i tymczasowy cwd |
| `__main__.py` w korzeniu | Build: sukces bez uwag; EXE: kod 1, `__main__.__spec__ is None` | Pozorny sukces pakowania |
| `main.pyw` | Build i uruchomienie poprawne, oczekiwany tekst na stdout | Przypadek kontrolny; nie dowodzi pełnej obsługi GUI |
| `logo.png` odczytywane przez program | Rzeczywisty EXE zgłosił brak zasobu | Klasyfikacja ikony wyłącza plik z danych |
| Poprawny Python z przykładem Markdown w napisie | Oryginał wypisał `REAL PROGRAM`, konwersja `EXAMPLE`, wynik `ok=True` | Konwerter zastępuje program treścią literału |
| Główny i zagnieżdżony `requirements.txt` | Analiza wybrała wersję `requests` z `examples/requirements.txt`, bez uwagi | Błędne pierwszeństwo manifestów |
| Samo `-c constraints.txt` z pinem `numpy` | Analiza dodała `numpy` do instalacji | Constraint błędnie staje się wymaganiem |
| `src/demo/main.py` importuje `demo.helper` | Analiza dodała `demo` do zewnętrznych paczek | Niespójny model korzeni importów |
| `importlib.import_module('PIL.Image')` | Hidden import obecny, lista paczek pusta | Rozpoznany import nie zasila instalacji zależności |
| Pojedynczy TXT z fence i `import helper` | Lokalny `helper.py` pominięty, zaproponowano paczkę `helper` | Domknięcie importów liczone przed konwersją |
| TXT w UTF-16 | Skaner zaklasyfikował go jako dane, `no_python_found` | Skaner i konwerter dekodują niespójnie |
| Zmiana źródła po analizie i dodanie pliku | Workspace zawierał nowe treści, plan zachował stare zależności | Plan nie utrwala zaakceptowanego stanu |
| Konflikt wersji, potem udane instalacje osobno | Kontrolowana atrapa uv: `failed_packages=()` | Orkiestracja dopuszcza niespójne wymagania; nie był to rzeczywisty test resolvera |
| Brak pliku walidatora | `validate_target_syntax` zwróciło `None` | Niewykonana kontrola jest traktowana jak brak błędów |
| Pakowanie walidatora w EXElent.exe | Inspekcja self-builda: brak jawnego dołączenia `_targetcheck.py` | Luka wynikająca z konfiguracji, do sprawdzenia na spakowanym produkcie |

## 3. Co już istnieje i co należy zachować

| Poprzednie zadania | Obecny stan implementacji | Pozostała praca |
|---|---|---|
| A01 | Publikacja pod wolną nazwą przez staging na woluminie docelowym | Zachować ochronę poprzedniej wersji; domknąć anulowanie i walidację publikacji |
| A02 | GUI wykonuje gotowy plan; konwersje są w `BuildPlan` | Inwentarz, utrwalenie treści i kontrola zmian źródeł |
| A03 | Kwalifikowane entrypointy, zwykłe pakiety, część `src/` i domknięcia importów | Główny `__main__.py`, wspólny model importów, diagnostyka nieobsługiwanych układów |
| A04 | Zachowanie względnych ścieżek danych; ONEDIR z `--contents-directory .` | Trwałe zapisy, brakujące zasoby, kolizje i lista w UI |
| A05–A06 | Naprawa tokenowa, mapa linii, konwersje z zachowaniem podkatalogów, blokada kolizji TXT/PY | Sprawdzenie poprawnego wejścia przed usuwaniem otoczki, dekodowanie, podgląd |
| A07 | `packaging.Requirement`, PEP 621, podstawowa obsługa Poetry, uwagi o importach spoza manifestu, ręczne moduły w GUI | Semantyka constraints, pierwszeństwo manifestów, importy dynamiczne/lokalne, walidacja obsługi Poetry |
| A08 | Blokowanie `failed_packages`, walidator docelowego Pythona, wykrywanie modułów odrzuconych przez PyInstaller | Spójność całego środowiska, walidator w dystrybucji, widoczne ostrzeżenia po sukcesie |
| A09–A11 | Token w części operacji, ograniczony odczyt prefiksu, preflight na docelowy Python | Pełne anulowanie, analiza w tle, powiązanie szacunków z planem |
| A12–A13 | Działania dla `executable_path`, izolacja workspace między instancjami | Podsumowanie i przewijanie, usługa poza CLI, wspólne AST, ochrona współdzielonego stanu |
| A14 | Testy UI izolują `LOCALAPPDATA`; istnieją workflow CI, golden i release | Poszerzenie regresji i rzeczywistych prób; powiązanie wydania z bramkami |

Istnienie mechanizmu nie oznacza wykonania wszystkich dawnych kryteriów akceptacji. Szczególnie A02, A05, A07 i A08 pozostają funkcjonalnie niedomknięte.

## 4. Zasady realizacji

- Nie modyfikować źródłowego projektu. Pracować na kopii zaakceptowanego wejścia.
- Nie wykonywać kodu wejściowego podczas analizy, konwersji ani walidacji składni. Uruchomienia regresyjne dotyczą kontrolowanych programów testowych; uruchomienie programu użytkownika pozostaje jego jawną akcją.
- Brak potwierdzenia kompletności nie może zamieniać się w sukces. Błąd walidatora i konflikt zależności to odrębne, widoczne wyniki.
- Wszystkie przewidywalne błędy przekazywać jako `Issue` z kodem i kontekstem; dostarczać PL i EN razem ze zmianą rdzenia.
- Plan opisuje źródła, konwersje, importy, zasoby, wymagania, target i wybory użytkownika. Metadane postępu lub szacunku nie wyznaczają zakresu budowania.
- Jeden kontekst docelowy Pythona i Windows obowiązuje w markerach, resolverze, walidacji, środowisku i backendzie.
- Kolejne publikacje zachowują poprzednie artefakty i dane. Sprzątanie dotyczy wyłącznie własnej sesji.
- Rdzeń pozostaje niezależny od Qt. GUI i CLI korzystają z tej samej usługi.
- Przed komendami Python/pytest/ruff/uv ustalać interpreter przez narzędzie środowiska PyCharm. Oddzielać interpreter deweloperski od targetu EXE.
- Każdy P0/P1 zaczynać od utrwalenia reprodukcji. Testować zachowanie publicznego kontraktu, a przy problemach pakowania również uruchomiony EXE.

## 5. Priorytety i zależności

P0: utrata danych. P1: zmiana programu, niekompletny lub niedziałający EXE, fałszywy sukces. P2: odporność, UX i utrzymanie. Podzadania UI ujawniające błąd P1 dostarczać razem z jego naprawą.

| ID | Zadanie | Priorytet | Powiązanie z A | Zależności |
|---|---|---|---|---|
| B01 | Trwałe zapisy i polityka ONEFILE/ONEDIR | P0 | A04 | Wspólny kontrakt zasobów z B07 |
| B02 | Konwersja TXT zachowująca program | P1 | A05–A06 | Brak |
| B03 | Poprawne uruchomienie skryptu i pakietu | P1 | A03 | Brak dla naprawy `__main__.py`; integracja z B04 |
| B04 | Wspólny model importów i zależności wykrytych | P1 | A03, A07 | B02 dla TXT |
| B05 | Manifesty bez utraty semantyki | P1 | A07 | Brak; integracja z B04 |
| B06 | Spójne środowisko i powtarzalne rozwiązanie wymagań | P1 | A08 | B05; blokadę fallbacku wdrożyć od razu |
| B07 | Kompletny, jawny zestaw zasobów | P1 | A04 | Kontrakt B01; integracja z B08 |
| B08 | Utrwalony plan i kontrolowana materializacja | P1 | A02, A06, A10 | Brak dla inwentarza; integracja z B02/B04/B07 |
| B09 | Obowiązkowa walidacja także w EXElent.exe | P1 | A08, A14 | Brak dla naprawy walidatora |
| B10 | Anulowanie całego procesu | P2 | A09 | Integracja z B08/B09/B14 |
| B11 | Analiza w tle i odporne I/O | P2 | A10, A13 | B08 dla wspólnego zakresu |
| B12 | Preflight zgodny z finalnym planem | P2 | A11 | B04–B06, B10 |
| B13 | Przejrzysty przegląd i wiarygodny wynik | P1/P2 | A12 | Dostarczane wraz z odpowiednimi B01–B12 |
| B14 | Usługa rdzenia, sesje i zachowanie bezpiecznej publikacji | P2 | A01, A13 | Stopniowo wraz z B08/B10 |
| B15 | Macierz regresji, wydanie i dokumentacja | P1 | A14 | Przez cały czas realizacji |

## 6. Zadania

### B01. Trwałe zapisy i polityka uruchomienia

Pliki: [apptype.py](../../../exelent/analysis/apptype.py), [launcher.py](../../../exelent/build/launcher.py), [planning.py](../../../exelent/planning.py), [models.py](../../../exelent/models.py).

Problem: alias `open` i `Image.save` omijają heurystykę, a ONEFILE ustawia cwd na `_MEIPASS`. Wynik zapisu może zniknąć wraz z katalogiem rozpakowania.

- [ ] Rozdzielić w kontrakcie katalog zasobów paczki, roboczy katalog uruchomienia i miejsce trwałych danych.
- [ ] Przyjąć zachowawczy domyślny tryb ONEDIR, dopóki polityka ONEFILE nie zapewnia trwałego cwd. Brak rozpoznanego zapisu nie jest dowodem, że program niczego nie zapisuje.
- [ ] Nie używać tymczasowego `_MEIPASS` jako domyślnego miejsca względnych zapisów. Dla ONEFILE ustalić jawny trwały cwd, np. katalog EXE; odmowa zapisu ma dać zrozumiałą diagnostykę.
- [ ] Powiązać odczyt zasobów z B07: źródła używające względnego `open('config.json')` muszą otrzymać zgodny układ. Jeśli pojedynczy EXE nie zapewnia tej zgodności, rekomendować ONEDIR i wyjaśnić przyczynę.
- [ ] Nie przepisywać dowolnych ścieżek w cudzym kodzie ani nie przedstawiać heurystyki jako gwarancji. Jawne zapisy do `__file__`/`_MEIPASS` i inne nieobsługiwane wzorce opisać przed budowaniem, jeśli zostały rozpoznane.
- [ ] Wyjaśnić konsekwencje ręcznego wyboru ONEFILE oraz odmowy dostępu w docelowej lokalizacji. Zachować ochronę danych z poprzednich wersji.

Akceptacja: rzeczywiste EXE dla aliasu `open`, `Path.open` i Pillow `.save` pozostawiają wynik po zakończeniu procesu, również po uruchomieniu z obcego cwd. Odczyt istniejących zasobów nadal działa. Test obejmuje zalecany tryb oraz ręcznie wybrany ONEFILE; przypadek bez gwarantowanej zgodności otrzymuje widoczne ograniczenie zamiast zapewnienia o bezpieczeństwie zapisu.

### B02. Konwersja TXT i dekodowanie

Pliki: [textconv.py](../../../exelent/analysis/textconv.py), [scanner.py](../../../exelent/analysis/scanner.py), [project.py](../../../exelent/analysis/project.py), modele i UI podglądu.

- [ ] Dodać reprodukcję poprawnego Pythona z blokiem Markdown w napisie wielowierszowym: konwersja musi zachować `REAL PROGRAM`, nie uruchamiać `EXAMPLE`.
- [ ] Po dekodowaniu najpierw sprawdzić całe wejście kompilatorem składni. Poprawnego programu nie poddawać usuwaniu fences, etykiet, numeracji ani promptów.
- [ ] Dla niepoprawnego wejścia rozpoznawać otoczkę bez naruszania literałów. Niejednoznacznych fragmentów nie naprawiać przez zgadywanie.
- [ ] Dla wielu bloków pokazać ich granice i sposób wyboru lub połączenia. Nie scalać automatycznie alternatywnych programów bez przeglądu.
- [ ] Zachować kroki konwersji i mapę linii w analizie i planie, tak aby podgląd oraz późniejszy błąd wskazywały oryginalny TXT.
- [ ] Ujednolicić dekodowanie skanera i konwertera: UTF-8 BOM, UTF-16, wspierane starsze kodowania oraz kontrolowany błąd uszkodzonego BOM. Dla `.py` respektować deklarację kodowania.
- [ ] Zachować odtwarzanie podkatalogów i blokady kolizji TXT/PY; walidować docelową ścieżkę konwersji względem workspace.

Akceptacja: testy poprawnych literałów, fences wewnątrz napisów, numerowanej treści literału, tabów, raw/bytes/f-stringów, pustego i niejednoznacznego wejścia. Powtórna konwersja nie zmienia wyniku. Skan projektu i pojedynczego TXT w UTF-16 znajdują program. Golden sprawdza zachowanie skonwertowanego EXE, nie tylko istnienie pliku.

### B03. Entry point skryptu i pakietu

Pliki: [entrymodule.py](../../../exelent/build/entrymodule.py), [launcher.py](../../../exelent/build/launcher.py), [pyinstaller.py](../../../exelent/build/pyinstaller.py), analiza entrypointu.

- [ ] Rozróżnić samodzielny skrypt, moduł pakietu i pakiet z `__main__.py` w modelu punktu wejścia.
- [ ] Naprawić główny `__main__.py`, unikając konfliktu z modułem launchera. Sposób zbierania przez PyInstaller i uruchamiania musi wynikać z jednego kontraktu.
- [ ] Zachować semantykę `__name__`, `__package__`, importów względnych i argumentów programu dla wspieranego sposobu uruchomienia.
- [ ] Zwracać diagnostykę niejednoznacznego wyboru, kolizji nazw lub nieobsługiwanego układu; nie wybierać przypadkowego modułu z `sys.path`.

Akceptacja: golden dla `main.py`, `main.pyw`, głównego `__main__.py`, `pkg/main.py`, `pkg/__main__.py` i `src/pkg/main.py`. Każdy program wykonuje konkretną oczekiwaną czynność i kończy się oczekiwanym kodem; przypadek GUI sprawdza również podsystem PE. Zachować testy importów względnych i uruchomienia z obcego cwd.

### B04. Jeden model importów

Pliki: [scanner.py](../../../exelent/analysis/scanner.py), [entrypoint.py](../../../exelent/analysis/entrypoint.py), [apptype.py](../../../exelent/analysis/apptype.py), [resolve.py](../../../exelent/deps/resolve.py), plan i resolver entrypointu.

- [ ] Wyznaczać wspólnie korzenie importów, kwalifikowane nazwy modułów i ich pliki. Używać tych danych w grafie entrypointu, zależnościach i argumentach PyInstallera.
- [ ] Lokalnego `src/demo` nie traktować jako pakietu do pobrania. Nazwa folderu `src` nie może zastępować nazw znajdujących się w nim pakietów.
- [ ] Stałe importy dynamiczne kierować zarówno do hidden imports, jak i rozpoznania lokalnego modułu lub zewnętrznej dystrybucji, z istniejącymi aliasami, np. `PIL → Pillow`.
- [ ] Domknięcie importów pojedynczego TXT liczyć z treści po konwersji. Włączać potrzebne lokalne źródła bez rozszerzania zakresu do całego folderu.
- [ ] Ręczne moduły kierować przez ten sam mechanizm; walidować nazwy i ujawniać niepewne mapowanie modułu na dystrybucję.
- [ ] Dla namespace packages, konfliktów wielkości liter i niejednoznacznych korzeni wdrożyć obsługę albo jawną diagnostykę ograniczenia.
- [ ] Przekroczenie limitu domknięcia nie może dawać niekompletnego zestawu przedstawionego jako gotowy do niezawodnego builda.

Akceptacja: regresje trzech przypadków z tabeli dowodów; golden `src/` z absolutnym importem własnego pakietu, dynamicznego Pillow oraz pojedynczego TXT z lokalnym helperem. Test potwierdza brak próby instalowania lokalnego modułu z indeksu. Zachować przypadki pakietów, `__init__.py`, podmodułów i importów względnych.

### B05. Manifesty i semantyka wymagań

Pliki: [scanner.py](../../../exelent/analysis/scanner.py), [resolve.py](../../../exelent/deps/resolve.py), modele, plan i środowisko.

- [ ] Główny `requirements.txt` ma pierwszeństwo przed zagnieżdżonymi manifestami. Manifesty podkatalogów uwzględniać przez jawne referencje lub wybór; ich kolejność na dysku nie może zmieniać wyniku.
- [ ] Przechowywać osobno wymagania instalacyjne i constraints. Wpis w `-c` ogranicza wersję, ale sam nie nakazuje instalacji.
- [ ] Preferować przekazanie zachowanych manifestów i constraints do uv, z poprawną bazą ścieżek w kopii roboczej. Nie odtwarzać całej semantyki pip przez spłaszczanie linii.
- [ ] Dla nieobsługiwanych opcji, lokalnych referencji, błędnych wymagań, cykli i brakujących plików zwracać diagnostykę; nie usuwać ich bez śladu.
- [ ] Ocenić markery względem rzeczywistego targetu, bez sztywnego założenia patcha `.0`; sprawdzać również zgodność `requires-python` projektu.
- [ ] Zachować PEP 621, zaimplementowaną obsługę Poetry i uwagi o importach spoza deklaracji. Sprawdzić ograniczenia Poetry: zakresy, prerelease, markery, warianty i lokalne ścieżki; niewspieranego warunku nie poszerzać po cichu.
- [ ] Przechowywać pochodzenie zależności: manifest, import statyczny, dynamiczny lub wpis użytkownika.

Akceptacja: główny manifest wygrywa niezależnie od układu podkatalogów; samo `-c` nie instaluje `numpy`, lecz ogranicza jego wersję, jeśli jest potrzebne. Działają `-r`, extras, markery i przypięcia. Błędny lub niewspierany wpis jest widoczny. Semantyka constraints: [dokumentacja pip](https://pip.pypa.io/en/stable/user_guide/#constraints-files).

### B06. Spójność środowiska

Pliki: [env.py](../../../exelent/runtime/env.py), [cli.py](../../../exelent/cli.py), plan i diagnostyka.

- [ ] Po nieudanym rozwiązaniu całego zestawu zatrzymywać budowanie. Usunąć ścieżkę, w której udane instalacje osobno kasują znaczenie zbiorowego błędu.
- [ ] Jeśli pojedyncze próby pozostaną narzędziem diagnostycznym, nie używać ich środowiska jako dowodu gotowości; wynik nadal musi zawierać pierwotny konflikt.
- [ ] Instalować spójne rozwiązanie pełnego zestawu, uwzględniające narzędzia budowania. Po instalacji sprawdzać zgodność deklarowanych wersji, zależności przechodnich i docelowego interpretera.
- [ ] Zachować rozróżnienie zależności wymaganych, opcjonalnych i nierozstrzygniętych. Nie traktować pominięcia wymaganej paczki jako ostrzeżenia pozwalającego na sukces.
- [ ] Zapisywać rozstrzygnięte wersje i wersje narzędzi w raporcie builda, aby umożliwić odtworzenie problemu.
- [ ] Zachować pełną diagnostykę instalacji, również gdy PyInstaller nie został uruchomiony.
- [ ] Umożliwić pracę z kompletnym cache bez bezwarunkowej blokady za brak połączenia z `pypi.org`; brak wymaganego artefaktu offline ma dawać konkretny błąd.

Akceptacja: konflikt dwóch pinów i konflikt zależności przechodnich blokują wywołanie backendu. Test rzeczywistego resolvera używa kontrolowanych lokalnych paczek, bez zależności od zmieniającego się indeksu. Poprawny zestaw przechodzi kontrolę spójności. Udokumentować stan cache i warunki powtórnego builda offline.

### B07. Zasoby i ich układ

Pliki: [scanner.py](../../../exelent/analysis/scanner.py), [models.py](../../../exelent/models.py), [planning.py](../../../exelent/planning.py), [workspace.py](../../../exelent/build/workspace.py), [pyinstaller.py](../../../exelent/build/pyinstaller.py), UI.

- [ ] Ikona aplikacji może być równocześnie zasobem runtime. Wybór `logo.png` jako ikony nie może usuwać go z danych.
- [ ] Zastąpić wyłącznie rozszerzeniową kwalifikację jawnym inwentarzem kandydatów na zasoby, z wykluczeniami i możliwością korekty. Nie dołączać automatycznie całego folderu użytkownika.
- [ ] Umożliwić dodanie m.in. `.html`, `.toml` i własnych formatów; pokazać źródło, rozmiar i względną lokalizację w paczce.
- [ ] Utrwalić mapowanie zasobów w planie. Wykrywać kolizje między zasobami, generowanym launcherem, ikoną, nazwą EXE i innymi plikami wynikowymi, z uwzględnieniem Windows.
- [ ] Stosować tę samą mapę w workspace i backendzie oraz politykę odczytu z B01.
- [ ] Zmiana lub zniknięcie zasobu po zaakceptowaniu planu wymaga kontrolowanego wyniku B08.

Akceptacja: golden odczytuje `logo.png`, `config.toml`, `templates/index.html` i zagnieżdżone dane z obcego cwd. Zasób użyty jako ikona nadal można odczytać. Kolizje są wykrywane przed PyInstallerem; testy obu trybów odpowiadają jawnej polityce B01.

### B08. Utrwalony plan i materializacja

Pliki: [models.py](../../../exelent/models.py), [project.py](../../../exelent/analysis/project.py), [planning.py](../../../exelent/planning.py), [workspace.py](../../../exelent/build/workspace.py).

- [ ] Dodać do planu inwentarz zaakceptowanych źródeł, konwersji, manifestów, zasobów i ikony oraz wersję/identyfikator planu.
- [ ] Utrwalić treść wejścia albo jej skróty. Przed publikowaniem kopii roboczej sprawdzić, czy skopiowane bajty odpowiadają zaakceptowanej analizie; sam mtime nie jest wystarczającym kontraktem.
- [ ] Zastąpić nieograniczone `copytree` kopiowaniem inwentarza. Nowe pliki nie mogą wejść do builda bez ponownej analizy.
- [ ] Zachować jeden zestaw limitów plików i bajtów dla skanowania, analizy i materializacji. Niepełny skan wymaga zawężenia wejścia lub jawnej obsługi ograniczenia.
- [ ] Ograniczyć ścieżki wynikowe do workspace; określić zachowanie symlinków, junctions i referencji zewnętrznych, bez niekontrolowanego wyjścia poza zaakceptowany zakres.
- [ ] Materializować do własnego stagingu sesji i udostępniać backendowi dopiero kompletną kopię. Błędy I/O i anulowanie sprzątają tylko ten staging.
- [ ] Plan ma być niemutowalny również wewnętrznie. Konwersje i szacunki muszą odnosić się do tej samej jego wersji.

Akceptacja: zmiana, usunięcie i dodanie pliku po analizie nie prowadzą do niezauważonej zmiany programu; zmiana podczas kopiowania jest wykrywana. Pojedynczy plik nie kopiuje Pobranych. Limit skanu obowiązuje także przy kopiowaniu. Testy obejmują odmowę dostępu, brak miejsca i niedozwolone ścieżki.

### B09. Walidator w dystrybucji i kontrola artefaktu

Pliki: [validate.py](../../../exelent/build/validate.py), [_targetcheck.py](../../../exelent/build/_targetcheck.py), [build_exelent.py](../../../build_exelent.py), backend i modele wyniku.

- [ ] Zapewnić dostępność kodu walidatora po spakowaniu EXElenta: jako jawny zasób albo kod przekazywany docelowemu interpreterowi. Nie polegać na istnieniu źródłowego `.py` obok modułu w zamrożonym produkcie.
- [ ] Rozdzielić wynik „składnia poprawna”, „składnia błędna”, „walidacja niewykonana/awaria” i „anulowano”. Brak skryptu, interpreter z błędem lub niepoprawny protokół nie mogą oznaczać `None` rozumianego jako sukces.
- [ ] Wprowadzić ustrukturyzowaną odpowiedź walidatora, zawierającą względną ścieżkę i linię; nie rozpoznawać błędu po dowolnym tabulatorze na stdout.
- [ ] Walidować pełny zaakceptowany zestaw źródeł, w tym `.pyw` i konwersje, rzeczywistym docelowym interpreterem, z ograniczeniem czasu i anulowaniem.
- [ ] Zachować kontrolę modułów odrzuconych przez PyInstaller jako dodatkową ochronę, nie zastępstwo niewykonanego sprawdzenia.
- [ ] Sprawdzać strukturę artefaktu przed publikacją: oczekiwany niepusty EXE, właściwy typ pliku i zadeklarowane składniki. Stan „utworzono” oddzielić od „zweryfikowano uruchomienie”.

Akceptacja: brak walidatora i uszkodzona odpowiedź blokują pakowanie z nazwanym błędem. Kod z `return` poza funkcją i kod niezgodny z targetem są odrzucane. Test na zbudowanym EXElent.exe potwierdza działanie kontroli, a następnie poprawne zbudowanie i uruchomienie kontrolnego EXE.

### B10. Anulowanie i procesy

Pliki: `runtime/bootstrap.py`, `runtime/env.py`, `runtime/procs.py`, `build/workspace.py`, `build/validate.py`, `build/pyinstaller.py`, `build/publish.py`, workery UI.

- [ ] Wspólny token obejmuje sprawdzenia wstępne, pobieranie uv/Pythona, kopiowanie, instalację, walidację, pakowanie i publikację.
- [ ] Wprowadzić sprawdzanie tokena między plikami i porcjami danych oraz skończone timeouty operacji sieciowych i oczekiwania na proces.
- [ ] Oddzielić zamknięcie stdout/stderr od zakończenia procesu. Po EOF nadal sprawdzać anulowanie, zamiast przechodzić do bezterminowego `wait()`.
- [ ] Po `kill_tree` również ograniczać `wait`, `communicate` i dołączenie wątku czytającego. Nieudane zakończenie potomków musi być widoczne.
- [ ] Zdefiniować punkt zatwierdzenia publikacji: anulowanie przed atomową zmianą nazwy usuwa staging; po skutecznej finalizacji zachować artefakt i zwrócić wynik zgodny z rzeczywistym stanem.
- [ ] Natychmiast pokazywać „Przerywanie…”, a końcowy wynik odróżniać od awarii. Anulowany token przed startem nie uruchamia niepotrzebnego bootstrapu.

Akceptacja: kontrolowane procesy milczące, z zamkniętym stdout i z potomkami kończą obsługę anulowania w zadeklarowanym budżecie. Przyjąć do 5 s reakcji dla lokalnych kontrolowanych operacji; wyjątki dla blokującego I/O muszą mieć skończony timeout i opisany limit. Testy synchronizować zdarzeniami, nie długim arbitralnym `sleep`. Nie pozostają niezarządzane procesy ani uszkodzona poprzednia publikacja.

### B11. Analiza w tle i odporne I/O

Pliki: `ui/app.py`, nowy worker analizy, `analysis/scanner.py`, `analysis/project.py`, model analizy.

- [ ] Przenieść analizę z głównego wątku Qt, dodać stan pracy, anulowanie i identyfikator żądania.
- [ ] Starszy wynik ani sygnał zakończenia nie może zastąpić analizy nowego wyboru.
- [ ] Przewidywalne błędy odczytu, dekodowania i dostępu do katalogu zamieniać na diagnostykę z plikiem lub lokalizacją.
- [ ] Ujednolicić limity i wykluczenia także w wykrywaniu innych języków. Nie wykonywać dodatkowego nieograniczonego `rglob` po ograniczonym skanie.
- [ ] Rozpoznawanie prefiksu nie może po cichu zerować grafu importów dużego pliku; gdy analiza jest niepełna, zgłosić to.
- [ ] Współdzielić sparsowane źródła między etapami, zamiast wielokrotnie tworzyć AST.

Akceptacja: podczas kontrolowanej długiej analizy pętla Qt obsługuje zdarzenia, a użytkownik może anulować lub wybrać nowe wejście. Brak dostępu, znikający plik, uszkodzone kodowanie i przekroczenie limitu dają czytelne stany. Stary wynik nie zmienia nowego ekranu.

### B12. Preflight zgodny z planem

Pliki: `ui/preflight.py`, `ui/app.py`, `ui/screen_review.py`, `deps/sizes.py`, modele szacunków.

- [ ] Wiązać każde obliczenie z identyfikatorem planu i targetu. Zmiana modułów lub zależności unieważnia wynik i uruchamia właściwe przeliczenie.
- [ ] Czyścić poprzedni wynik przy starcie. Nie pokazywać szacunku poprzedniego projektu podczas oczekiwania.
- [ ] Nie zastępować referencji do wątku, który nie zakończył się po `stop()`. Odrzucać spóźnione sygnały starych zadań.
- [ ] Odróżnić wynik kompletny, częściowy, brak cache, offline i błąd resolvera. Niewiadoma nie jest `0 B` ani „nic do pobrania”.
- [ ] Rozdzielić transfer, zajętość środowiska i szacowany rozmiar artefaktu. Uwzględniać tylko brakujące dane cache oraz jasno opisywać udział uv, Pythona i narzędzi.
- [ ] Używać docelowej zgodności wheel i zależności przechodnich. Nie przedstawiać rozmiaru EXE jako wielkości pobierania w dialogu.

Akceptacja: dopisanie modułu zmienia szacunek finalnego planu; spóźniony wynik A nie nadpisuje B. Częściowy cache zmniejsza transfer, nie deklarowany rozmiar aplikacji. Offline i timeout nie dają fałszywego zera. Wyliczanie ani oczekiwanie na nie nie blokuje obsługi GUI.

### B13. Przegląd, postęp i wynik GUI/CLI

Pliki: `ui/screen_review.py`, `ui/screen_build.py`, `ui/app.py`, `ui/rows.py`, `i18n/`, CLI i raporty.

- [ ] **P1:** pokazywać `BuildResult.issues` również po sukcesie pakowania; udostępniać raport zawierający uwagi analizy, instalacji i backendu.
- [ ] Rozróżnić „utworzono”, „utworzono z ostrzeżeniami” i potwierdzone uruchomienie. Sam przycisk „Uruchom” nie jest dowodem poprawności aplikacji.
- [ ] Przed buildem prezentować zakres wejścia, entrypoint, konwersje, zasoby, zależności, target, tryb i pełny cel publikacji; umożliwić zmianę celu.
- [ ] Udostępnić podgląd oryginału TXT, wyniku i zmian. Wyjaśnić ograniczenia ręcznych modułów i automatycznego rozpoznania zależności.
- [ ] Rozróżniać blocker i ostrzeżenie tekstem oraz ikoną; wskazywać czynność pozwalającą rozwiązać problem.
- [ ] Zapewnić przewijanie długiego przeglądu i dostępność akcji przy małym oknie oraz skalowaniu 100%, 150% i 200%.
- [ ] Udostępniać log na żywo z ograniczonym buforem widoku, zachowując pełny log na dysku. Nie czekać z pierwszym zapisem logu do zakończenia PyInstallera.
- [ ] W ONEDIR wskazywać cały folder do udostępnienia oraz osobno EXE do uruchomienia. Wyjaśniać powód rekomendacji trybu.
- [ ] Sprawdzić klawiaturę, fokus, długie ścieżki, zachowanie wyborów przy odświeżeniu języka i kompletność PL/EN, także launchera. Błędy otwarcia EXE/folderu mają dawać komunikat.

Akceptacja: uwaga pozostaje widoczna po udanym pakowaniu w GUI, CLI i raporcie. Ręczne przejście PY, TXT, projektu z zasobami, konfliktu zależności, anulowania i ponownego builda kończy się jasnym wynikiem. Automatyzować istotne zachowania; oceny wyglądu nie zastępować testami odtwarzającymi konstrukcję widgetów.

### B14. Usługa rdzenia, sesje i publikacja

Pliki: `cli.py`, `build/backend.py`, `build/workspace.py`, `build/publish.py`, `runtime/paths.py`, modele.

- [ ] Przenieść orkiestrację `execute_build` do usługi rdzenia poza CLI. CLI pozostaje adapterem argumentów i wyniku, a GUI nie importuje orkiestracji z adaptera konsolowego.
- [ ] Faktycznie wstrzykiwać `BuildBackend`, bez dodawania niepotrzebnego nowego backendu.
- [ ] Rozdzielić identyfikator instancji od identyfikatora próby builda i planu. Workspace i logi równoległych lub ponowionych prób nie mogą usuwać się wzajemnie.
- [ ] Zachować wolne nazwy publikacji i staging na woluminie docelowym. Sprawdzać kompletność według oczekiwanego inwentarza, nie wyłącznie łącznej liczby plików i sumy bajtów.
- [ ] Domknąć sprzątanie stagingu także przy błędzie jego weryfikacji. Nie usuwać istniejących danych aplikacji ani danych obcej sesji.
- [ ] Dla współdzielonego cache zapewnić bezpieczną inicjalizację i weryfikację narzędzia; uwzględnić blokady zapewniane już przez uv zamiast je dublować bez potrzeby.
- [ ] Ustalić zasady sprzątania przerwanych sesji i CLI. Nie usuwać katalogu aktywnej instancji na podstawie samego wieku.
- [ ] Skrócić komentarze historyczne; kontrakty i uzasadnienia pozostawić w kodzie, historię i decyzje przenieść do dokumentacji.

Akceptacja: test granic warstw przechodzi, GUI i CLI używają tej samej usługi, dwie instancje i kolejne próby są izolowane. Błąd kopiowania, weryfikacji, kolizja nazwy i anulowanie pozostawiają poprzedni EXE oraz `user-database.db` bajtowo niezmienione.

### B15. Regresje, CI, wydanie i dokumentacja

Pliki: `tests/`, `pyproject.toml`, `.github/workflows/ci.yml`, `.github/workflows/golden.yml`, `.github/workflows/release.yml`, `README.md`.

- [ ] Utrwalić reprodukcje B01–B09 w testach odpowiednich warstw. Atrapami sprawdzać orkiestrację, rzeczywistymi EXE granice pakowania i uruchomienia.
- [ ] Zachować dotychczasowe golden dla pakietów, zasobów, DLL numpy/pandas, konwersji i bezpiecznego ponownego builda; rozszerzyć je o poniższą macierz.
- [x] Sprawdzić zimny bootstrap targetu 3.12 z izolowanym cache uv/Pythona oraz powtórny build. Samo podstawienie `LOCALAPPDATA` nie jest dowodem pustego cache wszystkich narzędzi.
- [x] Testować zbudowany produkt EXElent.exe jako narzędzie budujące następny EXE, w tym dostępność walidatora B09.
- [x] Rozszerzyć istniejące workflow i filtry zmian o self-build, konfigurację zależności, helper walidatora i testy pipeline. Nie opisywać CI jako brakującego mechanizmu.
- [x] Powiązać wydanie z pozytywnymi wynikami wymaganych bramek dla tego samego commita: testy, lint/format, golden targetu i smoke test spakowanego produktu.
- [ ] Archiwizować logi i kontekst targetu z nieudanych buildów kontrolowanych. Raportować oddzielnie konfigurację deweloperską, target i wynik uruchomienia.
- [x] Zaktualizować README: rzeczywisty zakres obsługi, pojedynczy EXE versus folder, wymagania sieci/cache, ograniczenia analizy, trwałe dane i znaczenie komunikatu sukcesu.
- [x] Opisy ostrzeżeń systemowych i antywirusowych nie mogą przedstawiać każdego alertu jako potwierdzonego fałszywego alarmu; komunikat ma odzwierciedlać to, co narzędzie rzeczywiście ustaliło.

Macierz minimalna:

| Obszar | Przypadki | Oczekiwany dowód |
|---|---|---|
| Entry point | PY, PYW, główny `__main__`, pakiet, `src/` | Uruchomienie właściwego programu, kod wyjścia, dla GUI podsystem PE |
| Importy | Względne, podmoduły, własny pakiet `src/`, dynamiczne, TXT z helperem | Kompletna instalacja/paczka i oczekiwane zachowanie |
| TXT | Poprawny literał z fence, naprawa, UTF-16, kolizje, podkatalogi | Zachowane znaczenie i ścieżki; właściwe numery linii |
| Dane | Alias zapisu, Pillow save, logo, TOML, HTML, podkatalogi | Odczyt działa; zapis istnieje po zakończeniu EXE |
| Wymagania | Root/nested, `-r`, `-c`, markery, extras, Poetry, konflikty | Właściwy spójny zestaw; blocker przed pakowaniem przy konflikcie |
| Plan | Zmiana/usunięcie/dodanie pliku, limit, wyjście ścieżką poza workspace | Brak niezauważonej zmiany zakresu lub treści |
| Walidator | Źródła i spakowany EXElent, brak helpera, zły protokół, niezgodny target | Rozróżnienie błędu programu i niewykonanej kontroli |
| Środowisko | Windows/Python 3.12, pusty cache, ponowny build, offline | Pełny bootstrap i zgodny z cache wynik |
| Odporność | Spacje/polskie znaki, obcy cwd, brak miejsca/ACL, kolizje publikacji | Kontrolowany wynik bez utraty danych |
| Procesy/UI | Milczący proces, EOF przed końcem, potomkowie, anulowanie, spóźnione wyniki | Skończony czas obsługi i aktualny stan GUI |

## 7. Etapy dostarczenia

1. **Zabezpieczenie danych i znaczenia programu:** B01, B02, naprawa głównego `__main__.py` z B03, natychmiastowa blokada niespójnego fallbacku z B06 i naprawa dostępności/wyniku walidatora B09. Towarzyszące komunikaty i regresje są częścią etapu.
2. **Spójny opis wejścia:** inwentarz B08, wspólny model importów B04, semantyka manifestów B05 oraz zasoby B07. Domknięcie B03 i kontroli środowiska B06. Golden obejmuje pełny przepływ, nie tylko argumenty backendu.
3. **Odporność i aktualny stan pracy:** B10–B12 oraz niezbędne zmiany sesji i usługi B14. Odbiór obejmuje błędy I/O, anulowanie i zmianę wyboru podczas analizy/preflightu.
4. **Domknięcie produktu:** pozostałe B13/B14, ręczna ocena GUI, dokumentacja i wszystkie bramki B15, w tym test spakowanego EXElenta na target 3.12.

Nie odkładać widoczności błędów i ostrzeżeń do etapu 4. B15 obowiązuje w każdym etapie. Po zielonym odpowiednim zestawie testów nie powtarzać kosztownych prób bez zmiany kodu, nowego błędu lub nierozstrzygniętego ryzyka.

## 8. Warunki zakończenia i zapis odbioru

- [ ] Żaden kontrolowany zapis objęty deklarowaną obsługą nie ginie po zakończeniu EXE.
- [ ] Konwersja poprawnego Pythona nie zmienia jego znaczenia; niejednoznaczne wejście wymaga rozstrzygnięcia.
- [ ] Build odpowiada zaakceptowanym bajtom i zakresowi planu, także przy równoległej zmianie źródeł.
- [ ] Wszystkie wspierane entrypointy, importy i zasoby przechodzą rzeczywiste uruchomienia kontrolowanych EXE.
- [ ] Konflikt lub brak wymaganej zależności, niewykonana walidacja i niekompletny artefakt nie kończą się sukcesem.
- [ ] Ostrzeżenia pozostają widoczne po udanym pakowaniu, a GUI nie utożsamia utworzenia EXE z weryfikacją aplikacji.
- [ ] Poprzednie artefakty i dane przetrwały udaną, nieudaną i anulowaną publikację kolejnej wersji.
- [ ] Analiza i preflight nie blokują GUI, anulowanie ma sprawdzone limity, starsze wyniki nie nadpisują nowego wyboru.
- [ ] Zimny bootstrap 3.12, powtórny build i spakowany EXElent.exe zostały rzeczywiście sprawdzone.
- [ ] Dokumentacja i PL/EN opisują wdrożone zachowanie, a każde ograniczenie jest jawne i uzasadnione.

Przy odbiorze każdego Bxx dopisać: commit, zrealizowane kryteria, polecenia i wyniki testów, wersje interpreterów/narzędzi, wynik uruchomień EXE oraz ewentualny jawny zakres pozostały. Nie oznaczać całego zadania jako wykonanego wyłącznie dlatego, że jego podstawowy mechanizm istnieje.

## 9. Punkt wznowienia — 2026-09-12

Ostatni commit przy wznowieniu: `4428754` (B14). W katalogu roboczym były rozpoczęte,
niezacommitowane zmiany B15: osiem dodatkowych przypadków golden oraz CI/self-build.
Pierwotne nowe kroki nazwane smoke testami sprawdzały tylko rozmiar lub nagłówek MZ;
nie uruchamiały produktu ani nie sprawdzały dostępności walidatora. Zastąpiono je
testem zachowania spakowanego programu.

### Historia mechanizmów (nie pełny odbiór zadań)

| Zadanie | Commit(y) | Dostarczony mechanizm |
|---|---|---|
| B01 | `e16759c` | Domyślny ONEDIR i trwały cwd |
| B02 | `28d42b4` | Zachowanie poprawnego programu i wspólne dekodowanie |
| B03 | `06c1ec4`, `6fa629e` | Główny `__main__`, golden pakietu i PYW |
| B04 | `c74698a` | Importy src, dynamiczne i domknięcie TXT |
| B05 | `f75d7d6` | Pierwszeństwo manifestu głównego i podstawy constraints |
| B06 | `fc64af5` | Konflikt zbiorowy nie znika po pojedynczych instalacjach |
| B07 | `67dd5bd` | Ikona pozostaje zasobem runtime |
| B08 | `d3229ea` | Inwentarz i hashe zamiast copytree |
| B09 | `54dc93c` | Kod walidatora osadzony w module, awaria kontroli jako blocker |
| B10 | `633b419` | Rozszerzenie tokena i timeoutów |
| B11 | `7409aa8` | Worker analizy i diagnostyka I/O |
| B12 | `ee80c51` | Identyfikator zadania preflight i status wyniku |
| B13 | `49b8331` | Ostrzeżenia po sukcesie |
| B14 | `b023e3b`, `4428754` | Usługa rdzenia, backend, sesje, numery prób i weryfikacja uv |

### Kontynuacja B15 w katalogu roboczym

- Rzeczywisty `tests/test_product_smoke.py`: produkt z `--cli` i raportem JSON,
  zimne katalogi EXElenta/uv/Pythona, target 3.12, odrzucenie `return` poza funkcją,
  dwa buildy i uruchomienia EXE oraz zachowanie poprzedniego EXE i zapisanych danych.
- Reużywalny workflow `product.yml`; CI i golden wykonują test produktu.
  Istniejący release ma dodatkowe bramki lint/format/golden/smoke przed dotychczasowym
  krokiem publikacji, dla tego samego commita i dokładnie sprawdzonego EXE.
- Dokończenie ośmiu rozpoczętych golden: import względny, UTF-16, logo jako zasób,
  TOML/HTML, root/nested requirements, konflikt pinów, polskie znaki i spacje.
  Asercje sprawdzają też kod wyjścia i właściwy kod błędu konfliktu.
- Naprawa brakujących suffixów TOML/HTML w skanerze (ujawniona przez nową macierz B07).
- Naprawa regresji B14: `os.kill(pid, 0)` na Windows wysyła zdarzenie konsoli,
  zamiast bezpiecznie sprawdzać proces. Powodowało to `KeyboardInterrupt` w całym
  przebiegu testów. Windows używa teraz `OpenProcess`/`WaitForSingleObject` bez
  wysyłania sygnałów; niepewny/uszkodzony PID zachowuje sesję.
- README opisuje ONEDIR/ONEFILE, trwałe dane, ograniczenia zasobów i importów,
  wymagania sieci/cache oraz różnicę między pakowaniem i uruchomieniem.
- Uporządkowanie formatowania zaległego po wcześniejszych etapach.
- `tests/test_local_resolver.py`: rzeczywisty uv rozwiązuje lokalne, kontrolowane
  wheele przy wyłączonym indeksie. Konflikt pinów i konflikt przechodni blokują
  backend; poprawny zestaw instaluje oczekiwane wersje. Wheel narzędzia pakowania
  jest atrapą, dlatego test nie stanowi dowodu działania PyInstallera.

### Wyniki wykonane lokalnie

- Środowisko deweloperskie: Python **3.13.5**, pytest **9.1.1**, PyInstaller **6.16.0**,
  PySide6 **6.11.2**, uv targetu **0.8.17**, Windows 11 build 26100.
- `pytest -m "not slow" -q`: **840 zaliczonych**, 39 odznaczonych, 41,16 s
  (przed dodaniem trzech testów lokalnego resolvera).
- `pytest tests/test_local_resolver.py -m slow -q`: **3 zaliczone**, 17,68 s.
- `ruff check .`: bez błędów; `ruff format --check .`: **113 plików zgodnych**.
- Self-build przez `build_exelent.build_command()`, z przekierowaniem wyłącznie
  katalogów wynikowych do `build/verification-20260912/`: kod 0.
- `tests/test_product_smoke.py`: **1 zaliczony**, 56,13 s; po końcowej zmianie tekstów
  PL/EN i odświeżeniu self-builda **1 zaliczony**, 36,87 s. Rzeczywisty EXE zapisuje
  `SELF-BUILD-OK 3.12.11`; walidator spakowanego produktu zwraca
  `target_syntax_error`, `bad.py`, linia 1 dla `return` poza funkcją.
- Self-build lokalny powstał na deweloperskim 3.13.5; EXE budowane przez niego
  używają targetu **3.12.11**. Workflow self-builda jest ustawiony na 3.12,
  ale wykonania tego workflow na GitHub nie deklarujemy jako sprawdzonego lokalnie.
- Raporty i artefakt: `build/verification-20260912/` (ignorowane przez Git).
  Końcowy produkt: `build/verification-20260912/product-final/EXElent.exe`.
- `pytest tests/test_golden_builds.py -m slow -q`: **36 zaliczonych**, 826,74 s,
  bez błędów i pominięć (raport `golden.xml`). Wszystkie osiem rozpoczętych
  przypadków B15 zostało rzeczywiście wykonanych.
- `pytest tests/ui/test_screen_build.py -q`: **48 zaliczonych**, 1,18 s po zmianie
  tekstów PL/EN. Komunikaty o antywirusie nie deklarują już automatycznie fałszywego alarmu.
- Kontrola workflow przez inspekcję IDE osiągnęła timeout — nie stanowi dowodu
  walidacji GitHub Actions. Workflow nie uruchamiano zdalnie w tej sesji.
- Zmiany tej kontynuacji pozostają w katalogu roboczym, bez nowego commita.

Dokumentacja kontroli procesów: [os.kill](https://docs.python.org/3/library/os.html#os.kill),
[OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess),
[WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject).

### Zakres pozostały

Nie ma podstaw do oznaczenia całych B01–B15 jako odebranych. Pozostają m.in. pełna
semantyka manifestów/constraints i kontrola spójności środowiska (B05/B06), wybór
zasobów i kolizje (B07), pełny kontrakt wersji planu (B08), ścisły protokół walidatora
i kontrola PYW (B09), wszystkie limity anulowania (B10), pełny zakres preflightu
i przeglądu UI (B11–B13) oraz ręczna ocena GUI przy skalowaniu 100/150/200%.
Offline pozostaje ograniczeniem: usługa nadal wymaga sieci w preflight.

Nowe automatyczne wysyłanie EXE i diagnostyki do GitHub Artifacts zostało odrzucone
przez automatyczny przegląd uprawnień (brak jawnej zgody na pliki i miejsce eksportu).
Nowe workflow wykonują kontrole bez dodawania tego eksportu; raporty zostają lokalnie
w katalogach `build/`. Istniejący mechanizm publikacji release pozostaje osobnym krokiem.

### Proponowany zakres archiwizacji po zgodzie

Miejsce: GitHub Actions Artifacts repozytorium `PerlessMtFuji/EXElent` (adres `origin`
sprawdzony lokalnie). Retencja: 7 dni; wysyłanie po nieudanym przebiegu testów.

| Archiwum | Pliki do dołączenia |
|---|---|
| `golden-diagnostics` | `build/golden.xml` oraz logi kontrolowanych buildów z `build/golden/**/EXElent/logs/*.log` |
| `product-diagnostics` | `build/product-smoke.xml`, `context.json`, `cold.json`, `invalid.json`, `warm.json`, `cold.log`, `warm.log` z podkatalogu kontrolowanej próby |

Pliki zawierają wyniki i diagnostykę programów testowych, wersje narzędzi oraz ścieżki
runnera. To konkretny zakres do zatwierdzenia przed dodaniem kroku eksportu do workflow.
