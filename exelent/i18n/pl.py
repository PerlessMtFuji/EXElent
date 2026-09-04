"""Polskie zdania dla kodów rdzenia.

Tekst pisany do osoby nietechnicznej: bez żargonu, każdy komunikat mówi co się
stało i co z tym zrobić. Klucze pochodzą z kodu — test kompletności liczy je
z `exelent/`, więc nowy kod Issue bez zdania zapala się na czerwono.
"""

CATALOG: dict[str, str] = {
    # analiza
    "no_python_found": (
        "W folderze {dir} nie widzę programu w Pythonie. "
        "Sprawdź, czy wskazany folder zawiera pliki z kodem."
    ),
    "other_language": (
        "Ten kod jest napisany w innym języku niż Python (pliki {suffix}). "
        "EXElent obsługuje na razie tylko Pythona."
    ),
    "multiple_entry_points": (
        "Widzę tu więcej niż jeden program: {first} i {second}. Wybierz, który zbudować."
    ),
    "scan_truncated": (
        "Ten folder jest bardzo duży ({files} plików). "
        "Sprawdź, czy na pewno wskazałeś właściwe miejsce."
    ),
    "single_file_too_many": (
        "Ten plik wciąga bardzo wiele innych plików z tego samego folderu. "
        "Buduję sam wskazany plik — jeśli to za mało, wskaż cały folder z programem."
    ),
    "txt_syntax_error": (
        "W pliku {file} jest błąd w linii {line}: {detail}. Popraw go i spróbuj ponownie."
    ),
    "no_entry_point": (
        "Nie wiem, od którego pliku zaczyna się Twój program. "
        "Wskaż ten, który normalnie uruchamiasz."
    ),
    # ostrzeżenia o kodzie
    "server_app": (
        "To jest serwer ({framework}). Po uruchomieniu okno będzie wyglądać na bezczynne "
        "— program czeka na połączenia."
    ),
    "external_tool": (
        "Twój program używa zewnętrznego narzędzia ({tool}), którego nie da się spakować "
        "do EXE. Osoba uruchamiająca program musi je mieć zainstalowane."
    ),
    "secrets_in_code": (
        "W kodzie znalazłem coś, co wygląda na klucz dostępu. Da się go odczytać z gotowego "
        "EXE — nie udostępniaj tego pliku publicznie."
    ),
    "dynamic_import_unresolved": (
        "Twój program wczytuje biblioteki w trakcie działania. "
        "Może się zdarzyć, że któraś nie trafi do EXE."
    ),
    "heavy_packages": (
        "Ten program używa dużych bibliotek ({packages}). Plik EXE może mieć kilkaset "
        "megabajtów, a budowanie potrwa dłużej."
    ),
    # środowisko
    "no_network": (
        "Brak połączenia z internetem. Pierwsze budowanie wymaga pobrania narzędzi "
        "— połącz się i spróbuj ponownie."
    ),
    "low_disk_space": "Za mało miejsca na dysku: wolne {free_gb} GB, potrzeba około {needed_gb} GB.",
    "uv_download_failed": (
        "Nie udało się pobrać narzędzi. Sprawdź połączenie z internetem i ustawienia zapory."
    ),
    "env_setup_failed": (
        "Nie udało się przygotować środowiska do budowania. Sprawdź połączenie z internetem "
        "i spróbuj ponownie."
    ),
    # build
    "build_cancelled": "Budowanie przerwane.",
    "cancel_incomplete": (
        "Budowanie przerwane, ale jeden z procesów mógł zostać w tle. Jeśli następne "
        "budowanie zachowa się dziwnie, uruchom komputer ponownie."
    ),
    "artifact_vanished": (
        "Gotowy plik {name} zniknął w trakcie budowania. Najczęściej robi to program "
        "antywirusowy — dodaj wyjątek i spróbuj ponownie."
    ),
    "package_not_found": (
        "Nie udało się pobrać jednej z potrzebnych bibliotek. "
        "Sprawdź, czy jej nazwa w kodzie jest poprawna."
    ),
    "module_not_found": (
        "Brakuje biblioteki {module}. Dodaj ją do listy dodatków albo popraw import w kodzie."
    ),
    "packages_failed": (
        "Nie udało się dołączyć tych bibliotek: {packages}. Plik EXE powstanie, ale może "
        "się nie uruchomić u osoby, której go dasz."
    ),
    "antivirus_blocked": (
        "Program antywirusowy zablokował zapis pliku. "
        "Dodaj folder EXElent do wyjątków i spróbuj ponownie."
    ),
    "cloud_file_unavailable": (
        "Plik {file} jest trzymany w chmurze i nie ma go na tym komputerze. Otwórz go raz "
        "w Eksploratorze plików albo zaznacz „Zawsze zachowuj na tym urządzeniu”, "
        "i spróbuj ponownie."
    ),
    "file_in_use": (
        "Któryś z plików jest w tej chwili używany przez inny program. "
        "Zamknij go i spróbuj ponownie."
    ),
    "dest_in_use": (
        "Nie mogę zapisać wyniku w {path} — poprzednia wersja programu jest teraz używana. "
        "Zamknij ją i spróbuj ponownie."
    ),
    "access_denied": (
        "Windows odmówił dostępu do pliku. Sprawdź, czy masz uprawnienia do tego folderu."
    ),
    "path_too_long": (
        "Ścieżka do plików jest za długa dla Windows. Przenieś folder z kodem bliżej "
        "korzenia dysku, na przykład do C:\\kod."
    ),
    "ssl_proxy": (
        "Połączenie zostało przechwycone przez zaporę lub serwer proxy. "
        "W sieci firmowej może być potrzebna pomoc administratora."
    ),
    "disk_full": "Skończyło się miejsce na dysku w trakcie budowania.",
    "recursion_limit": "Budowanie napotkało bardzo złożoną strukturę kodu i przerwało analizę.",
    "script_failed": "Zbudowany program nie uruchomił się poprawnie.",
    "encoding_problem": "Któryś z plików ma nietypowe kodowanie znaków.",
    "unexpected_error": (
        "Coś poszło nie tak i nie umiem tego nazwać ({error}). "
        "Dołącz raport do zgłoszenia — z nim da się to naprawić."
    ),
    # fazy postępu
    "download_uv": "Pobieram narzędzia…",
    "install_python": "Przygotowuję Pythona…",
    "create_env": "Tworzę środowisko…",
    "install_packages": "Pobieram dodatki…",
    "build_start": "Zaczynam budowanie…",
    "analyze": "Analizuję Twój kod…",
    "hooks": "Przygotowuję biblioteki…",
    "libraries": "Zbieram pliki…",
    "package": "Pakuję do EXE…",
    "collect": "Kończę…",
    "done": "Gotowe!",
    "progress_bytes": "{done} z {total}",
    "progress_eta": "zostało {eta}",
    # ekran 1 — wskazanie folderu
    "drop_headline": "Przeciągnij tu folder z kodem",
    "drop_browse": "Wybierz folder",
    "drop_recent": "Ostatnie",
    # ekran 2 - co zrozumialem
    "review_headline": "Oto co zrozumiałem",
    "review_entry": "Program główny",
    "review_kind": "Rodzaj programu",
    "review_name": "Nazwa pliku",
    "review_icon": "Ikona",
    "review_pick_icon": "wybierz",
    "review_icon_filter": "Obrazy (*.png *.jpg *.jpeg *.ico)",
    "review_deps_title": "Potrzebne dodatki — zostaną pobrane automatycznie",
    "single_file_extra": "Dołączam też: {files}",
    "review_mode": "Postać wyniku",
    "review_recommended_suffix": "(zalecane)",
    "review_restore": "przywróć zalecane",
    "review_build": "Stwórz EXE",
    "review_back": "← Wstecz",
    "kind_windowed": "Program w oknie",
    "kind_console": "Program konsolowy",
    "mode_onefile": "Jeden plik EXE",
    "mode_onedir": "Folder z programem",
    # ekran 3 - budowanie i wynik
    "build_cancel": "Przerwij",
    "build_open_folder": "Pokaż w folderze",
    "build_run": "Uruchom",
    "build_save_report": "Zapisz raport",
    "build_report_filter": "Plik tekstowy (*.txt)",
    "build_report_github": "Zgłoś na GitHubie",
    "build_again": "Zrób następny program",
    "build_back_to_review": "← Wróć do ustawień",
    "build_show_log": "Pokaż szczegóły",
    "build_hide_log": "Ukryj szczegóły",
    "build_success": "Gotowe! {name} — {size}",
    "build_failed_title": "Nie udało się",
    "build_failed_unknown": (
        "Nie rozpoznaję tego błędu. Zapisz raport albo zgłoś go — pomożesz naprawić EXElent."
    ),
    "antivirus_note": (
        "Jeśli program antywirusowy oznaczy ten plik jako podejrzany, to fałszywy alarm "
        "typowy dla programów tworzonych w ten sposób. Możesz dodać plik do wyjątków."
    ),
}
