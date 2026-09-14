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
    "txt_multiple_blocks": (
        "Plik {file} zawiera {count} bloków kodu (linie {ranges}). Zostały połączone "
        "po kolei — jeśli któryś jest alternatywną wersją, a nie kontynuacją, zostaw "
        "tylko ten właściwy."
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
    "frozen_path_pattern": (
        "Twój kod używa {pattern} — po spakowaniu wskazuje on katalog rozpakowania, "
        "nie folder z EXE. Ścieżki budowane na jego podstawie mogą czytać lub pisać "
        "w nieoczekiwane miejsca. EXElent nie przepisuje Twojego kodu; sprawdź te ścieżki "
        "przed udostępnieniem EXE."
    ),
    "size_estimate": (
        "Gotowy program zajmie około {low}–{high} MB. Najwięcej miejsca zajmą: {packages}."
    ),
    "size_estimate_large": (
        "Gotowy program zajmie około {low}–{high} MB, a budowanie potrwa dłużej niż zwykle. "
        "Najwięcej miejsca zajmą: {packages}."
    ),
    # manifesty zależności
    "requirements_missing": (
        "Lista wymagań wskazuje na plik {file}, którego nie ma — lista dodatkowych "
        "bibliotek może być niepełna."
    ),
    "requirements_cycle": (
        "Pliki wymagań wskazują na siebie w kółko (przez {file}); powtórzenie zostało pominięte."
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
    "requirements_unsupported_option": (
        "Opcja {option} w {file} nie jest obsługiwana — została pominięta. "
        "Lista bibliotek może być niepełna."
    ),
    "version_mismatch": (
        "Biblioteka {package} została zainstalowana w wersji {installed}, a zadeklarowana "
        "była {declared}. Upewnij się, że program działa z tą wersją."
    ),
    "requirements_invalid_spec": (
        "Wymaganie „{spec}” nie mogło zostać odczytane i zostało pominięte — "
        "lista bibliotek może być niepełna."
    ),
    "poetry_version_fallback": (
        "Ograniczenie wersji Poetry „{constraint}” nie mogło być w pełni zinterpretowane — "
        "użyto jedynie wersji minimalnej. Sprawdź, czy zainstalowana wersja jest poprawna."
    ),
    "requires_python_mismatch": (
        "Projekt deklaruje requires-python = „{declared}”, co nie obejmuje docelowego "
        "Pythona {target}. Budowanie może się udać, ale program nie był projektowany "
        "pod tę wersję."
    ),
    "asset_collides_with_generated": (
        "Plik {file} ma taką samą nazwę jak plik tworzony przy budowaniu ({generated}). "
        "Zmień mu nazwę, żeby uniknąć konfliktu."
    ),
    "asset_path_collision": (
        "Dwa pliki trafiają pod tę samą ścieżkę w gotowym programie: {file_a} i {file_b}. "
        "W systemie Windows nazwy różniące się tylko wielkością liter oznaczają ten sam plik "
        "— zmień nazwę jednego z nich."
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
        "Gotowy plik {name} zniknął w trakcie budowania. Sprawdź folder wynikowy "
        "i historię ochrony systemu, aby ustalić przyczynę."
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
        "Zapis pliku został zablokowany. Sprawdź historię ochrony programu "
        "antywirusowego i treść alertu przed ponowną próbą."
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
    "download_transfer": "Transfer: {count} brakujących paczek, około {size}",
    "download_transfer_cached": "Transfer paczek: 0 B — wszystkie archiwa są w cache",
    "download_transfer_unknown": "Transfer: nie udało się ustalić bez zgadywania",
    "download_environment_min": (
        "Środowisko: co najmniej {size} (skompresowane archiwa; po rozpakowaniu będzie większe)"
    ),
    "download_environment_unknown": "Środowisko: rozmiar nieznany",
    "download_artifact_estimate": "Gotowy program: szacunkowo {low}–{high} MB",
    "download_artifact_unknown": "Gotowy program: brak wiarygodnego pomiaru dla tych paczek",
    "download_component_uv_cached": "uv jest na dysku",
    "download_component_uv_missing": "uv trzeba pobrać",
    "download_component_python_cached": "Python 3.12 jest na dysku",
    "download_component_python_missing": "Python 3.12 trzeba pobrać",
    "download_component_tools": "narzędzia budowania uwzględnione",
    "download_components": "Składniki: {components}",
    "dialog_download_title": "Potrzebne dodatki",
    "dialog_download_body": (
        "Do zbudowania programu trzeba pobrać {count} paczek — około {size}. "
        "Pobieranie odbywa się raz; następne budowania będą szybsze."
    ),
    "dialog_download_body_estimate": (
        "Do zbudowania programu może być potrzebne pobranie uv, Pythona, narzędzi "
        "i dodatków. Nie udało się sprawdzić wielkości transferu. Gotowy program "
        "zajmie szacunkowo {low}–{high} MB; te widełki nie są wielkością pobierania. "
        "Pobieranie odbywa się raz; następne budowania będą szybsze."
    ),
    "dialog_download_body_unknown": (
        "Do zbudowania programu może być potrzebne pobranie uv, Pythona i narzędzi "
        "budowania. Nie udało się wiarygodnie ustalić wielkości transferu."
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
    "review_deps_title": "Rozmiary przygotowania i gotowego programu",
    "review_extra_modules": "Brakuje modułu? Dopisz go tutaj",
    "review_extra_modules_placeholder": ("np. moja_wtyczka, pakiet.podmoduł — oddziel przecinkami"),
    "review_extra_modules_help": (
        "Dopisane nazwy trafiają do hidden imports. EXElent spróbuje mapować ich pierwszy "
        "człon na paczkę, ale prywatne wtyczki mogą wymagać własnego manifestu."
    ),
    "single_file_extra": "Dołączam też: {files}",
    "review_mode": "Postać wyniku",
    "review_target": "Docelowy Python",
    "review_destination": "Pełne miejsce publikacji",
    "review_destination_change": "Zmień miejsce publikacji…",
    "review_destination_pick": "Wybierz miejsce publikacji",
    "review_scope_title": "Zakres przyjęty do budowania",
    "review_scope_source": "Wejście: {path}",
    "review_scope_summary": (
        "Źródła: {sources} · konwersje TXT: {conversions} · zasoby: {resources} · "
        "zależności projektu: {dependencies}"
    ),
    "review_preview_button": "Pokaż oryginał, wynik i różnicę",
    "review_preview_title": "Podgląd konwersji — {file}",
    "review_preview_original": "Oryginał TXT",
    "review_preview_result": "Wynik Python",
    "review_preview_diff": "Różnica",
    "review_preview_unavailable": "Nie można już odczytać oryginalnego pliku.",
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
    "build_success": "Utworzono {name} — {size}. Uruchomienie nie zostało potwierdzone.",
    "build_success_warnings": (
        "Utworzono {name} z ostrzeżeniami — {size}. Uruchomienie nie zostało potwierdzone."
    ),
    "build_success_verified": "Utworzono i sprawdzono uruchomienie {name} — {size}.",
    "build_success_verified_warnings": (
        "Utworzono {name} z ostrzeżeniami i sprawdzono uruchomienie — {size}."
    ),
    "build_launch_started": (
        "System rozpoczął uruchamianie programu; EXElent nie potwierdza jego wyniku."
    ),
    "build_run_failed": "Nie udało się uruchomić programu: {error}",
    "build_open_failed": "Nie udało się otworzyć folderu wyniku: {error}",
    "build_failed_title": "Nie udało się",
    "build_failed_unknown": (
        "Nie rozpoznaję tego błędu. Zapisz raport albo zgłoś go — pomożesz naprawić EXElent."
    ),
    "antivirus_note": (
        "Jeśli antywirus zgłosi ostrzeżenie, sprawdź źródło programu i treść alertu. "
        "EXElent nie potwierdza bezpieczeństwa programu ani tego, że alarm jest fałszywy."
    ),
}
