"""Map Issue codes and progress phases to Polish and English sentences.

The completeness guard derives core requirements from `inventory` instead of
copying a list into the test. Review round 4 (I12) found that both planned
guards missed seven codes actually produced, including
`cloud_file_unavailable` from the previous round. A copied list becomes stale
silently, so users see a raw code while tests remain green.
"""

from string import Formatter

import pytest
from inventory import (
    DECLARED_DATA,
    DECLARED_DYNAMIC_ISSUES,
    DECLARED_DYNAMIC_PHASES,
    codes_with_non_literal_data,
    dynamic_issue_sites,
    dynamic_phase_sites,
    issue_data_keys,
    phase_keys,
)

from exelent.diagnostics.patterns import PATTERNS
from exelent.i18n import CATALOGS, current_language, describe, set_language, system_language, t
from exelent.models import Issue, Severity


@pytest.fixture(autouse=True)
def _reset_language():
    set_language("pl")
    yield
    set_language("pl")


def _placeholders(template: str) -> set[str]:
    return {name for _text, name, _spec, _conv in Formatter().parse(template) if name}


# --- completeness derived from code ---


def test_both_catalogs_have_identical_keys():
    assert set(CATALOGS["pl"]) == set(CATALOGS["en"])


def test_every_issue_code_the_core_can_produce_is_translated():
    missing = sorted(set(issue_data_keys()) - set(CATALOGS["pl"]))
    assert missing == [], f"codes without translations: {missing}"


def test_every_diagnostic_pattern_is_translated():
    codes = {code for _pattern, code, _severity in PATTERNS}
    assert codes <= set(CATALOGS["pl"])


def test_every_progress_phase_is_translated():
    missing = sorted(phase_keys() - set(CATALOGS["pl"]))
    assert missing == [], f"phases without translations: {missing}"


def test_the_inventory_still_sees_progress_phases():
    """Guard the phase scan because an empty set passes every completeness test."""
    phases = phase_keys()
    assert "install_packages" in phases, "the env.py phase disappeared from inventory"
    assert len(phases) > 8, f"phase inventory unexpectedly shrank to {len(phases)}"


def test_templates_only_ask_for_data_the_core_supplies():
    """Catch templates that request data the core never supplies.

    A `{dir}` placeholder without `dir` does not crash; it exposes braces in a
    user-facing sentence, so this quiet failure needs an explicit guard.
    """
    known = issue_data_keys()
    wrong = {}
    for lang, catalog in CATALOGS.items():
        for key, template in catalog.items():
            if key in known and (extra := _placeholders(template) - known[key]):
                wrong[f"{lang}:{key}"] = sorted(extra)
    assert wrong == {}, f"templates request data the core does not supply: {wrong}"


# --- guards for the guard itself ---


def test_the_inventory_sees_the_codes_that_recent_rounds_added():
    """Ensure the scan still finds data; an empty inventory would pass trivially."""
    codes = set(issue_data_keys())
    assert "cloud_file_unavailable" in codes, "the round-3 code disappeared from inventory"
    assert len(codes) > 25, f"inventory unexpectedly shrank to {len(codes)} codes"


def test_dynamic_issue_sites_are_declared():
    """Declare every runtime-built code that is invisible to the AST scan."""
    assert dynamic_issue_sites() == set(DECLARED_DYNAMIC_ISSUES)


def test_dynamic_progress_sites_are_declared():
    assert dynamic_phase_sites() == set(DECLARED_DYNAMIC_PHASES)


def test_codes_with_non_literal_data_are_declared():
    assert codes_with_non_literal_data() == set(DECLARED_DATA)


# --- layer behavior ---


def test_translation_switches_with_language():
    polish = t("no_network")
    set_language("en")
    assert t("no_network") != polish


def test_an_unknown_language_falls_back_to_english():
    set_language("de")
    assert current_language() == "en"


def test_parameters_are_interpolated():
    assert "ffmpeg" in t("external_tool", tool="ffmpeg")


def test_missing_key_returns_key_not_crash():
    assert t("missing-key") == "missing-key"


def test_describe_renders_issue_with_its_data():
    issue = Issue("external_tool", Severity.WARNING, {"tool": "tesseract"})
    assert "tesseract" in describe(issue)


def test_describe_tolerates_missing_parameters():
    assert describe(Issue("external_tool", Severity.WARNING)) != ""


def test_system_language_falls_back_to_english(monkeypatch):
    monkeypatch.setattr("locale.getlocale", lambda: (None, None))
    assert system_language() == "en"


def test_system_language_detects_polish(monkeypatch):
    monkeypatch.setattr("locale.getlocale", lambda: ("pl_PL", "cp1250"))
    assert system_language() == "pl"


def test_system_language_detects_the_form_windows_actually_returns(monkeypatch):
    """On Polish Windows, `locale.getlocale()` returns the English locale name.

    It yields `('Polish_Poland', '1250')`, not `pl_PL`. The test above supplies
    a POSIX form that this system never returns and therefore missed code that
    showed Polish users an English window.
    """
    monkeypatch.setattr("locale.getlocale", lambda: ("Polish_Poland", "1250"))
    assert system_language() == "pl"


def test_cloud_advice_never_mentions_the_antivirus():
    """Round 3 added cloud advice to avoid irrelevant antivirus troubleshooting."""
    for lang in CATALOGS:
        set_language(lang)
        text = t("cloud_file_unavailable", file="dane.py").lower()
        assert "antywirus" not in text and "antivirus" not in text
        assert "chmur" in text or "cloud" in text
