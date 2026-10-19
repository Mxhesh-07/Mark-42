"""Tier 2 H2 — redaction before anything leaves the process.

Two levels, and the whole point is the difference between them. Logs and crash
bundles get the full treatment; outbound model text gets credentials only,
because the user's email address is usually the content of the request, not a
leak in it.
"""

from agent import redact


GOOGLE_KEY = "AIza" + "A" * 35


def test_a_google_api_key_is_masked():
    out = redact.secrets(f"key is {GOOGLE_KEY} ok")
    assert GOOGLE_KEY not in out
    assert "<redacted-key>" in out


def test_an_openai_style_key_is_masked():
    out = redact.secrets("sk-" + "a" * 32)
    assert "sk-" + "a" * 32 not in out


def test_a_github_token_is_masked():
    out = redact.secrets("ghp_" + "a" * 36)
    assert "ghp_" not in out


def test_a_slack_token_is_masked():
    assert "xoxb" not in redact.secrets("xoxb-" + "a" * 32)


def test_an_aws_access_key_is_masked():
    out = redact.secrets("AKIA" + "ABCDEFGHIJKLMNOP")
    assert "AKIA" not in out


def test_a_jwt_is_masked():
    jwt = "eyJhbGciOiJIUzI1NiJ9." + "a" * 30 + "." + "b" * 30
    assert jwt not in redact.secrets(jwt)


def test_a_bearer_header_is_masked():
    out = redact.secrets("Authorization: Bearer abcdef1234567890")
    assert "abcdef1234567890" not in out
    assert "Bearer <redacted>" in out


def test_a_labelled_secret_is_masked_and_keeps_its_label():
    out = redact.secrets('api_key = "abcdef1234567890"')
    assert "abcdef1234567890" not in out
    assert out == "api_key=<redacted>"


def test_a_password_assignment_is_masked():
    out = redact.secrets("password: hunter2hunter2")
    assert "hunter2" not in out
    assert "password=<redacted>" == out


def test_a_private_key_block_is_masked_whole():
    block = ("-----BEGIN RSA PRIVATE KEY-----\n"
             "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWy\n"
             "-----END RSA PRIVATE KEY-----")
    out = redact.secrets("here it is:\n" + block)
    assert "MIIEpAIBAAKCAQEA" not in out
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert "<redacted-private-key>" in out


def test_a_url_password_is_masked_but_the_host_is_not():
    out = redact.secrets("https://user:hunter3@example.com/api")
    assert "hunter3" not in out
    assert "user" in out
    assert "example.com" in out


# --- card numbers -------------------------------------------------------------

def test_a_valid_card_number_is_masked():
    out = redact.secrets("card 4111 1111 1111 1111 on file")
    assert "4111" not in out
    assert "<card>" in out


def test_a_card_number_without_grouping_is_masked():
    assert "<card>" in redact.secrets("4111111111111111")


def test_an_arbitrary_long_number_is_left_alone():
    """A number that fails the Luhn check is not a card and must survive."""
    candidate = "1234 5678 9012 3456"
    assert redact.secrets(candidate) == candidate


def test_a_ten_digit_phone_number_is_not_treated_as_a_card():
    candidate = "9876543210"
    assert redact.secrets(candidate) == candidate


# --- the level difference -----------------------------------------------------

def test_the_secrets_level_keeps_an_email_address():
    text = "write to mahesh@example.com about the invoice"
    assert redact.secrets(text) == text


def test_the_secrets_level_keeps_a_home_path():
    text = r"save it to C:\Users\asus tuf\Desktop\notes.txt"
    assert redact.secrets(text) == text


def test_the_personal_level_masks_the_email():
    out = redact.personal("write to mahesh@example.com about the invoice")
    assert "mahesh@example.com" not in out
    assert "<email>" in out


def test_the_personal_level_masks_a_windows_home_path():
    out = redact.personal(r"save it to C:\Users\asus tuf\Desktop\notes.txt")
    assert "asus tuf" not in out
    assert "<home>" in out


def test_the_personal_level_masks_a_posix_home_path():
    out = redact.personal("write /home/mahesh/.ssh/id_rsa here")
    assert "mahesh" not in out


def test_the_personal_level_masks_a_phone_number():
    out = redact.personal("call +91 98765 43210 tonight")
    assert "98765" not in out
    assert "<number>" in out


# --- properties ----------------------------------------------------------------

def test_redaction_is_idempotent():
    text = f"api_key={GOOGLE_KEY} mail me@x.com 4111111111111111"
    assert redact.secrets(redact.secrets(text)) == redact.secrets(text)
    assert redact.personal(redact.personal(text)) == redact.personal(text)


def test_prose_without_credentials_is_untouched_at_the_secrets_level():
    text = "Summarise this page and tell me the three main risks."
    assert redact.outbound(text) == text


def test_outbound_walks_lists_and_dicts():
    payload = {"prompt": [f"key={GOOGLE_KEY}", {"note": "none here"}]}
    cleaned = redact.outbound(payload)
    assert GOOGLE_KEY not in cleaned["prompt"][0]
    assert cleaned["prompt"][1]["note"] == "none here"


def test_outbound_leaves_non_strings_alone():
    class Thing:
        pass

    thing = Thing()
    assert redact.outbound(thing) is thing
    assert redact.outbound([thing])[0] is thing


def test_redact_of_a_structured_value_masks_every_layer():
    out = redact.redact({"a": ["x@y.com", {"token": "sk-" + "b" * 20}]})
    assert out["a"][0] == "<email>"
    # The OpenAI-style pattern matches the *value* first, so the label is left
    # with a masked value; either way the token itself is gone.
    assert out["a"][1]["token"] == "<redacted-key>"
    assert "sk-" + "b" * 20 not in str(out)


def test_off_returns_the_value_unchanged():
    text = f"api_key={GOOGLE_KEY}"
    assert redact.redact(text, level="off") is text


# --- configuration -------------------------------------------------------------

def test_the_log_level_defaults_to_personal(write_policy):
    write_policy({"enabled": True})
    assert redact.level_for("log") == "personal"


def test_the_egress_level_defaults_to_secrets(write_policy):
    write_policy({"enabled": True})
    assert redact.level_for("egress") == "secrets"


def test_the_levels_are_configurable(write_policy):
    write_policy({"enabled": True,
                  "privacy": {"log_redaction": "secrets",
                              "egress_redaction": "off"}})
    assert redact.level_for("log") == "secrets"
    assert redact.level_for("egress") == "off"


def test_an_unknown_level_falls_back_to_the_safe_default(write_policy):
    write_policy({"enabled": True, "privacy": {"egress_redaction": "everything"}})
    assert redact.level_for("egress") == "secrets"


def test_findings_reports_what_would_change():
    assert redact.findings("plain words") == {}
    assert "secrets" in redact.findings(f"key={GOOGLE_KEY}")


def test_the_cli_reports_both_levels(write_policy, capsys):
    write_policy({"enabled": True})
    assert redact._cli([f"api_key={GOOGLE_KEY}"]) == 0
    assert "redacted" in capsys.readouterr().out


def test_the_cli_asks_for_text_instead_of_hanging_on_a_tty(capsys, monkeypatch):
    import sys as _sys

    class _Tty:
        def isatty(self):
            return True

    monkeypatch.setattr(_sys, "stdin", _Tty())
    assert redact._cli([]) == 2
    assert "usage" in capsys.readouterr().out


def test_the_cli_reads_piped_text(capsys, monkeypatch):
    import io
    import sys as _sys

    monkeypatch.setattr(_sys, "stdin", io.StringIO(f"key={GOOGLE_KEY}"))
    assert redact._cli([]) == 0
    assert GOOGLE_KEY not in capsys.readouterr().out


# --- the places it is used -----------------------------------------------------

def test_crash_bundles_still_redact():
    from agent import crash

    out = crash.redact(r"mail bob@example.com from C:\Users\bob\x.txt")
    assert "bob@example.com" not in out
    assert "<email>" in out
    assert "<home>" in out


def test_the_model_request_path_masks_credentials():
    import gemini_util

    payload = [f"api_key={GOOGLE_KEY}", "and a normal sentence"]
    cleaned = gemini_util._clean(payload)
    assert GOOGLE_KEY not in cleaned[0]
    assert cleaned[1] == "and a normal sentence"
    assert gemini_util._clean(cleaned) == cleaned     # safe to apply twice


def test_the_tier2_prompt_is_derived_from_the_cleaned_text():
    """Tier-2 routes through _text_plan(contents), which the SDK wrappers now
    build from the cleaned contents — so Groq/OpenRouter/Ollama get the same
    treatment as Gemini without their own hook."""
    import gemini_util

    plan = gemini_util._safe_plan(gemini_util._clean(f"api_key={GOOGLE_KEY}"), None)
    assert plan is not None
    assert GOOGLE_KEY not in plan[0]
    assert plan[2] is False


def test_a_multimodal_request_is_not_mangled():
    """_clean only walks strings, so Parts and images pass through untouched."""
    import gemini_util

    class Part:
        pass

    part = Part()
    contents = [part, f"api_key={GOOGLE_KEY}"]
    cleaned = gemini_util._clean(contents)
    assert cleaned[0] is part
    assert GOOGLE_KEY not in cleaned[1]
