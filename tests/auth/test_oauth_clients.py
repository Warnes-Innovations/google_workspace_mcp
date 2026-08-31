"""Tests for the multi-client OAuth registry and per-account client selection."""

import json

import pytest

from auth.google_auth import load_client_secrets_from_env, resolve_oauth_client
from auth.oauth21_session_store import OAuth21SessionStore
from auth.oauth_clients import (
    OAuthClient,
    OAuthClientRegistryError,
    load_registry_from_env,
    parse_registry_document,
)
from auth.oauth_config import OAuthConfig

REGISTRY_ENV_VARS = (
    "GOOGLE_OAUTH_CLIENTS_FILE",
    "GOOGLE_OAUTH_CLIENTS",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
)

THREE_CLIENT_DOC = {
    "default": "personal",
    "clients": {
        "personal": {"client_id": "personal-id", "client_secret": "personal-secret"},
        "work": {"client_id": "work-id", "client_secret": "work-secret"},
        "contract": {"client_id": "contract-id"},
    },
    "domains": {"warnes.net": "personal", "example.com": "work"},
    "emails": {"someone@example.com": "contract"},
}


@pytest.fixture(autouse=True)
def clear_registry_env(monkeypatch):
    """Every test starts from an unconfigured environment."""
    for name in REGISTRY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------
# Document parsing and validation
# --------------------------------------------------------------------------


def test_parses_multi_client_document():
    registry = parse_registry_document(THREE_CLIENT_DOC)

    assert len(registry) == 3
    assert registry.keys == ["contract", "personal", "work"]
    assert registry.default.key == "personal"
    assert registry.get("work").client_secret == "work-secret"


def test_client_without_secret_is_public():
    registry = parse_registry_document(THREE_CLIENT_DOC)
    contract = registry.get("contract")

    assert contract.client_secret is None
    assert contract.is_public is True


def test_blank_secret_is_treated_as_public_not_empty_secret():
    # A blank value in config means "no secret", not "a secret that is the
    # empty string" — the latter would be sent to Google as a real credential.
    registry = parse_registry_document(
        {"clients": {"a": {"client_id": "a-id", "client_secret": "   "}}}
    )

    assert registry.get("a").client_secret is None
    assert registry.get("a").is_public is True


@pytest.mark.parametrize(
    "document, expected_message",
    [
        ({}, "non-empty 'clients'"),
        ({"clients": {}}, "non-empty 'clients'"),
        ({"clients": {"a": "not-an-object"}}, "must be an object"),
        ({"clients": {"a": {}}}, "missing a non-empty string 'client_id'"),
        ({"clients": {"a": {"client_id": "   "}}}, "missing a non-empty string"),
        (
            {"clients": {"a": {"client_id": "x", "client_secret": 42}}},
            "non-string 'client_secret'",
        ),
        (
            {"clients": {"a": {"client_id": "x"}}, "default": "missing"},
            "is not defined in 'clients'",
        ),
        (
            {"clients": {"a": {"client_id": "x"}}, "domains": {"d.com": "nope"}},
            "refers to undefined client",
        ),
        (
            {"clients": {"a": {"client_id": "x"}}, "emails": {"e@d.com": "nope"}},
            "refers to undefined client",
        ),
        ({"clients": {"a": {"client_id": "x"}}, "domains": []}, "must be an object"),
        ("not-a-dict", "must be a JSON object"),
    ],
)
def test_malformed_documents_are_rejected(document, expected_message):
    with pytest.raises(OAuthClientRegistryError) as excinfo:
        parse_registry_document(document)
    assert expected_message in str(excinfo.value)


def test_client_describe_never_leaks_the_secret():
    client = OAuthClient(key="work", client_id="work-id", client_secret="s3cr3t")
    description = client.describe()

    assert "s3cr3t" not in description
    assert "work" in description


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


def test_exact_email_match_wins_over_domain():
    registry = parse_registry_document(THREE_CLIENT_DOC)

    # someone@example.com is mapped explicitly to "contract" while the
    # example.com domain maps to "work"; the more specific rule must win.
    assert registry.resolve("someone@example.com").key == "contract"
    assert registry.resolve("other@example.com").key == "work"


def test_domain_match():
    registry = parse_registry_document(THREE_CLIENT_DOC)
    assert registry.resolve("greg@warnes.net").key == "personal"


def test_unmapped_account_falls_back_to_default():
    registry = parse_registry_document(THREE_CLIENT_DOC)
    assert registry.resolve("stranger@elsewhere.org").key == "personal"


def test_resolution_is_case_insensitive():
    registry = parse_registry_document(THREE_CLIENT_DOC)

    assert registry.resolve("GREG@WARNES.NET").key == "personal"
    assert registry.resolve("  SomeOne@Example.COM  ").key == "contract"


def test_multi_client_without_default_returns_none_for_unmapped_account():
    # No default means an unmapped account is a configuration error, not a
    # silent authorization against an arbitrary project.
    document = dict(THREE_CLIENT_DOC)
    document.pop("default")
    registry = parse_registry_document(document)

    assert registry.default is None
    assert registry.resolve("stranger@elsewhere.org") is None
    assert registry.resolve("greg@warnes.net").key == "personal"


def test_single_client_is_its_own_default_without_being_named():
    registry = parse_registry_document({"clients": {"solo": {"client_id": "solo-id"}}})

    assert registry.default.key == "solo"
    assert registry.resolve("anyone@anywhere.com").key == "solo"


# --------------------------------------------------------------------------
# Environment loading
# --------------------------------------------------------------------------


def test_loads_registry_from_file(tmp_path, monkeypatch):
    path = tmp_path / "clients.json"
    path.write_text(json.dumps(THREE_CLIENT_DOC), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENTS_FILE", str(path))

    registry = load_registry_from_env()

    assert len(registry) == 3
    assert registry.resolve("greg@warnes.net").key == "personal"


def test_loads_registry_from_inline_json(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENTS", json.dumps(THREE_CLIENT_DOC))

    registry = load_registry_from_env()

    assert registry.resolve("other@example.com").key == "work"


def test_registry_file_takes_precedence_over_inline(tmp_path, monkeypatch):
    path = tmp_path / "clients.json"
    path.write_text(
        json.dumps({"clients": {"from-file": {"client_id": "file-id"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENTS_FILE", str(path))
    monkeypatch.setenv(
        "GOOGLE_OAUTH_CLIENTS",
        json.dumps({"clients": {"from-inline": {"client_id": "inline-id"}}}),
    )

    assert load_registry_from_env().keys == ["from-file"]


def test_malformed_registry_file_raises_rather_than_falling_back(tmp_path, monkeypatch):
    # Silently ignoring a broken registry would authorize accounts against
    # whichever client happened to remain configured.
    path = tmp_path / "clients.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENTS_FILE", str(path))
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "legacy-id")

    with pytest.raises(OAuthClientRegistryError) as excinfo:
        load_registry_from_env()
    assert "not valid JSON" in str(excinfo.value)


def test_missing_registry_file_raises(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "GOOGLE_OAUTH_CLIENTS_FILE", str(tmp_path / "does-not-exist.json")
    )

    with pytest.raises(OAuthClientRegistryError) as excinfo:
        load_registry_from_env()
    assert "could not read" in str(excinfo.value)


def test_legacy_single_client_env_still_works(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "legacy-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "legacy-secret")

    registry = load_registry_from_env()

    assert registry.keys == ["default"]
    assert registry.default.client_id == "legacy-id"
    assert registry.default.client_secret == "legacy-secret"
    assert registry.resolve("anyone@anywhere.com").key == "default"


def test_no_configuration_at_all_returns_none():
    assert load_registry_from_env() is None


# --------------------------------------------------------------------------
# OAuthConfig integration and backward compatibility
# --------------------------------------------------------------------------


def test_legacy_env_still_populates_client_id_and_secret(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "legacy-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "legacy-secret")

    cfg = OAuthConfig()

    assert cfg.client_id == "legacy-id"
    assert cfg.client_secret == "legacy-secret"
    assert cfg.is_configured() is True
    assert cfg.has_multiple_clients() is False


def test_config_exposes_default_client_of_a_registry(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENTS", json.dumps(THREE_CLIENT_DOC))

    cfg = OAuthConfig()

    assert cfg.client_id == "personal-id"
    assert cfg.has_multiple_clients() is True
    assert cfg.get_client_for_email("other@example.com").key == "work"
    assert cfg.get_client_by_key("contract").client_id == "contract-id"
    assert cfg.get_client_by_key("nonexistent") is None


def test_environment_summary_lists_keys_but_no_credentials(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENTS", json.dumps(THREE_CLIENT_DOC))

    summary = OAuthConfig().get_environment_summary()

    assert summary["registered_client_keys"] == ["contract", "personal", "work"]
    rendered = json.dumps(summary)
    assert "personal-secret" not in rendered
    assert "personal-id" not in rendered


def test_unconfigured_config_has_no_client(monkeypatch):
    cfg = OAuthConfig()

    assert cfg.client_id is None
    assert cfg.client_secret is None
    assert cfg.get_client_for_email("anyone@anywhere.com") is None


# --------------------------------------------------------------------------
# Flow-level client selection
# --------------------------------------------------------------------------


@pytest.fixture
def registry_config(monkeypatch):
    """Point auth.google_auth at a freshly built three-client config."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENTS", json.dumps(THREE_CLIENT_DOC))
    cfg = OAuthConfig()
    monkeypatch.setattr("auth.google_auth.get_oauth_config", lambda: cfg)
    return cfg


def test_resolve_by_email(registry_config):
    assert resolve_oauth_client(user_google_email="other@example.com").key == "work"


def test_explicit_client_key_wins_over_email(registry_config):
    # The callback passes the recorded key; it must not be second-guessed by
    # whatever the email would resolve to now.
    client = resolve_oauth_client(
        client_key="contract", user_google_email="greg@warnes.net"
    )
    assert client.key == "contract"


def test_unknown_client_key_raises_instead_of_falling_back(registry_config):
    # Falling back to the default would exchange the code against a different
    # Cloud project and surface as an opaque 'invalid_client' from Google.
    with pytest.raises(ValueError) as excinfo:
        resolve_oauth_client(client_key="retired-client")

    assert "no longer registered" in str(excinfo.value)


def test_absent_client_key_uses_default(registry_config):
    assert resolve_oauth_client().key == "personal"


def test_client_secrets_shape_is_confidential_for_a_client_with_a_secret():
    config = load_client_secrets_from_env(
        OAuthClient(key="work", client_id="work-id", client_secret="work-secret")
    )

    assert "web" in config
    assert config["web"]["client_id"] == "work-id"
    assert config["web"]["client_secret"] == "work-secret"


def test_client_secrets_reflect_the_environment_at_call_time(monkeypatch):
    # Regression: resolving the default client through the cached OAuthConfig
    # singleton made this function return whatever client the process started
    # with, ignoring the current environment entirely.
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "first-id")
    assert load_client_secrets_from_env()["installed"]["client_id"] == "first-id"

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "second-id")
    assert load_client_secrets_from_env()["installed"]["client_id"] == "second-id"


def test_client_secrets_are_none_when_environment_has_no_client():
    assert load_client_secrets_from_env() is None


def test_client_secrets_shape_is_installed_for_a_public_client():
    config = load_client_secrets_from_env(
        OAuthClient(key="contract", client_id="contract-id")
    )

    assert "installed" in config
    assert config["installed"]["client_id"] == "contract-id"
    assert config["installed"]["client_secret"] == ""


# --------------------------------------------------------------------------
# OAuth state round-trip
# --------------------------------------------------------------------------


def test_client_key_survives_the_state_round_trip(tmp_path):
    # The callback recovers the client from the persisted state, so the value
    # has to survive serialization to disk, not merely live in memory.
    state_file = tmp_path / "oauth_states.json"
    writer = OAuth21SessionStore(oauth_state_file=str(state_file))
    writer.store_oauth_state("state-abc", code_verifier="verifier", client_key="work")

    reader = OAuth21SessionStore(oauth_state_file=str(state_file))
    state_info = reader.validate_and_consume_oauth_state("state-abc")

    assert state_info is not None
    assert state_info.get("client_key") == "work"
    assert state_info.get("code_verifier") == "verifier"


def test_state_written_without_a_client_key_reads_back_as_none(tmp_path):
    # State entries created before multi-client support must still complete;
    # the callback treats a missing key as "the default client".
    state_file = tmp_path / "oauth_states.json"
    writer = OAuth21SessionStore(oauth_state_file=str(state_file))
    writer.store_oauth_state("state-legacy", code_verifier="verifier")

    reader = OAuth21SessionStore(oauth_state_file=str(state_file))
    state_info = reader.validate_and_consume_oauth_state("state-legacy")

    assert state_info is not None
    assert state_info.get("client_key") is None
