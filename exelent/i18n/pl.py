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
    "py_syntax_error": (
        "W pliku {file} jest błąd składni w linii {line}: {detail}. "
        "Tak napisany program się nie uruchomi — popraw go i spróbuj ponownie."
    ),
    "target_syntax_error": (
        "W pliku {file} jest błąd w linii {line}: {detail}. Kod nie kompiluje się docelowym "
        "Pythonem {version} — gotowy EXE nie zawierałby tego modułu i padłby na starcie. "
        "Popraw go i spróbuj ponownie."
    ),
    "txt_no_code": (
        "W pliku {file} nie ma żadnego kodu do uruchomienia — została sama otoczka z okna "
        "czatu albo pusty blok. Wklej program i spróbuj ponownie."
    ),
    "txt_collision": (
        "Plik {file} po zamianie na kod dałby {target}, ale taki plik już w projekcie jest. "
        "Zostaw tylko jedną wersję i spróbuj ponownie."
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
    "size_estimate": (
        "Gotowy program zajmie około {low}–{high} MB. Najwięcej miejsca zajmą: {packages}."
    ),
    "size_estimate_large": (
        "Gotowy program zajmie około {low}–{high} MB, a budowanie potrwa dłużej niż zwykle. "
        "Najwięcej miejsca zajmą: {packages}."
    ),
    # manifesty zależności (A07)
    "requirements_missing": (
        "Lista wymagań wskazuje na plik {file}, którego nie ma — lista dodatkowych "
        "bibliotek może być niepełna."
    ),
    "requirements_cycle": (
        "Pliki wymagań wskazują na siebie w kółko (przez {file}); powtórzenie zostało "
        "pominięte."
    ),
    "pyproject_unreadable": (
        "Nie udało się odczytać {file}, więc zadeklarowane w nim biblioteki zostały "
        "pominięte — rozpoznam je z kodu."
    ),
    "pyproject_dynamic_deps": (
        "{file} deklaruje biblioteki dynamicznie, więc rozpoznałem je z kodu."
    ),
    "dependency_not_declared": (
        "Twój kod używa biblioteki {package}, której nie ma na liście wymagań — "
        "dołączyłem ją, żeby program działał."
    ),
    "module_name_collision": (
        "Dwa pliki mają tę samą nazwę modułu „{module}” w różnych folderach ({files}). "
        "Jeden przesłoniłby drugi przy uruchomieniu — zmień nazwę jednego albo zostaw "
        "tylko ten potrzebny."
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
    "fence_label_removed": (
        "W pliku {file} pierwsza linia to sama etykieta z okna czatu — usunalem ja, "
        "zeby program dal sie zbudowac."
    ),
    "module_dropped": (
        "W pliku {file} jest błąd, przez który nie dał się on wczytać, więc nie trafił "
        "do gotowego programu. Popraw ten plik i zbuduj jeszcze raz."
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
    "required_package_failed": (
        "Nie udało się zainstalować wymaganej biblioteki: {packages}. Plik EXE NIE powstał, bo "
        "wywaliłby się u osoby, której byś go dał. Sprawdź nazwę biblioteki i połączenie z "
        "internetem, a potem spróbuj ponownie."
    ),
    "requirements_conflict": (
        "Potrzebne biblioteki mają sprzeczne wymagania co do wersji i nie da się ich pogodzić. "
        "Plik EXE NIE powstał — środowisko byłoby niespójne. Uzgodnij wersje w wymaganiach "
        "(np. w requirements.txt) i spróbuj ponownie."
    ),
    "source_changed_after_analysis": (
        "Pliki źródłowe zmieniły się po analizie ({files}). "
        "Plik EXE NIE powstał — zbudowany program mógłby się różnić od tego, co zaakceptowałeś. "
        "Spróbuj ponownie, żeby EXElent przeanalizował aktualny kod."
    ),
    "validation_failed": (
        "Nie udało się sprawdzić kodu docelowym Pythonem {version}, więc build został "
        "zatrzymany — to była awaria samej kontroli, nie potwierdzenie, że kod jest dobry. "
        "Spróbuj ponownie; jeśli się powtarza, zgłoś to. Szczegóły: {detail}"
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
    "publish_incomplete": (
        "Gotowy {name} nie skopiował się w całości do folderu docelowego. Nic nie zostało "
        "nadpisane — poprzednia wersja jest nietknięta. Zbuduj jeszcze raz."
    ),
    "publish_failed": (
        "Nie udało się zapisać gotowego programu w {path}. Nic nie zostało nadpisane — "
        "poprzednia wersja jest nietknięta. Sprawdź folder i spróbuj ponownie."
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
    "file_read_error": "Nie mogę odczytać {file} — pomijam.",
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
    "download_checking": "sprawdzam rozmiar…",
    "download_size": "{count} paczek — około {size} do pobrania",
    "download_nothing": "Wszystko już pobrane — budowanie ruszy od razu",
    "dialog_download_title": "Potrzebne dodatki",
    "dialog_download_body": (
        "Do zbudowania programu trzeba pobrać {count} paczek — około {size}. "
        "Pobieranie odbywa się raz; następne budowania będą szybsze."
    ),
    "dialog_download_body_estimate": (
        "Do zbudowania programu trzeba pobrać dodatki. Nie udało się sprawdzić "
        "dokładnego rozmiaru — gotowy program zajmie około {low}–{high} MB. "
        "Pobieranie odbywa się raz; następne budowania będą szybsze."
    ),
    "dialog_download_ok": "Pobierz i buduj",
    "dialog_download_cancel": "Anuluj",
    "dialog_download_dont_ask": "Nie pytaj ponownie",
    "settings_title": "Ustawienia",
    "settings_ask_download": "Pytaj przed pobieraniem dodatków",
    "settings_language": "Język",
    "settings_language_system": "Jak w systemie",
    # ekran 1 — wskazanie folderu
    "drop_headline": "Przeciągnij tu folder albo plik z kodem",
    "drop_analyzing": "Analizuję Twój kod…",
    "drop_browse": "Wybierz…",
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
    "review_extra_modules": "Brakuje modułu? Dopisz go tutaj",
    "review_extra_modules_placeholder": (
        "np. moja_wtyczka, pakiet.podmoduł — oddziel przecinkami"
    ),
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
    "onefile_no_resource_guarantee": (
        "Jeden plik EXE: dołączone pliki są rozpakowywane do katalogu tymczasowego, "
        "więc odczyt zasobu przez względną ścieżkę (np. open('config.json')) może się "
        "nie powieść. Jeśli program czyta pliki leżące obok siebie, wybierz „Folder z "
        "programem”. Zapisane pliki trafiają obok EXE i zostają."
    ),
    # ekran 3 - budowanie i wynik
    "build_cancel": "Przerwij",
    "build_cancelling": "Przerywanie…",
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
