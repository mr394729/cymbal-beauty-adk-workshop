import pytest

from agents.cymbal_store_ops import preflight


def test_a_valid_sign_in_passes_silently(monkeypatch):
    monkeypatch.setattr(preflight, "adc_problem", lambda: None)
    monkeypatch.setattr(preflight, "cli_problem", lambda: None)
    assert preflight.require_sign_in() is None
    assert preflight.require_sign_in(cli=True) is None


def test_an_expired_adc_stops_in_words_with_the_fix(monkeypatch):
    monkeypatch.setattr(preflight, "adc_problem", lambda: "Reauthentication is needed.")
    monkeypatch.setattr(preflight, "cli_problem", lambda: None)
    with pytest.raises(SystemExit) as stop:
        preflight.require_sign_in()
    text = str(stop.value)
    assert "nothing was run" in text and "Fix: gcloud auth application-default login" in text
    assert "gcloud auth login\n" not in text          # the CLI was not asked about, so its fix is not shown


def test_the_cli_is_checked_only_when_asked_and_both_fixes_are_listed(monkeypatch):
    monkeypatch.setattr(preflight, "adc_problem", lambda: "Reauthentication is needed.")
    monkeypatch.setattr(preflight, "cli_problem", lambda: "There was a problem refreshing your current auth tokens")
    with pytest.raises(SystemExit) as stop:
        preflight.require_sign_in(cli=True)
    text = str(stop.value)
    assert "Fix: gcloud auth application-default login" in text and "Fix: gcloud auth login" in text
    assert "uv run python scripts/check_env.py --stage prereqs" in text
