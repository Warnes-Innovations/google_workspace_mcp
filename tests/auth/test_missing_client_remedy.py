"""The remedy for "no OAuth client available" must fit the actual cause.

`is_configured()` is False for two opposite reasons, and the advice that fixes
one is a guaranteed no-op for the other. `load_registry_from_env` returns at the
first source it finds, so a configured registry takes precedence and the legacy
GOOGLE_OAUTH_CLIENT_ID is never read. An operator told to set it would see no
change and have no way to learn why.
"""

import json

import pytest

from auth.oauth_config import OAuthConfig

REGISTRY_ENV_VARS = (
    "GOOGLE_OAUTH_CLIENTS_FILE",
    "GOOGLE_OAUTH_CLIENTS",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
)

NO_DEFAULT_DOC = {
    "clients": {
        "personal": {"client_id": "personal-id", "client_secret": "ps"},
        "work": {"client_id": "work-id", "client_secret": "ws"},
    },
    "domains": {"example.com": "work"},
}


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    for name in REGISTRY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("MCP_ENABLE_OAUTH21", raising=False)


def test_nothing_configured_names_the_variables_that_would_work():
    remedy = OAuthConfig().missing_default_client_remedy()

    assert "GOOGLE_OAUTH_CLIENT_ID" in remedy
    assert "GOOGLE_OAUTH_CLIENTS_FILE" in remedy
    # Nothing to say about a default when there is no registry at all.
    assert "'default'" not in remedy


def test_registry_without_a_default_says_set_default(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENTS", json.dumps(NO_DEFAULT_DOC))
    remedy = OAuthConfig().missing_default_client_remedy()

    assert "'default'" in remedy
    # It names the clients, so the operator knows what to choose between.
    assert "personal" in remedy and "work" in remedy


def test_registry_remedy_says_the_legacy_variable_will_not_help(monkeypatch):
    # The load-bearing assertion. Without this the message could name the
    # default AND still leave "set GOOGLE_OAUTH_CLIENT_ID" standing beside it,
    # which is the contradiction that produced this defect.
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENTS", json.dumps(NO_DEFAULT_DOC))
    remedy = OAuthConfig().missing_default_client_remedy()

    assert "NOT take effect" in remedy
    assert "precedence" in remedy


def test_the_two_causes_get_different_remedies(monkeypatch):
    unconfigured = OAuthConfig().missing_default_client_remedy()
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENTS", json.dumps(NO_DEFAULT_DOC))
    with_registry = OAuthConfig().missing_default_client_remedy()

    assert unconfigured != with_registry


def test_the_claim_the_remedy_makes_is_actually_true(monkeypatch):
    """Verify the precedence the message asserts, rather than trusting it.

    The remedy tells the operator GOOGLE_OAUTH_CLIENT_ID will not take effect
    while a registry is configured. If that ever stopped being true the message
    would become the misleading one.
    """
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENTS", json.dumps(NO_DEFAULT_DOC))
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "legacy-id-that-should-be-ignored")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "legacy-secret")

    config = OAuthConfig()

    assert config.client_registry is not None
    assert config.client_registry.keys == ["personal", "work"]
    assert "legacy-id-that-should-be-ignored" not in config.client_registry.keys
    # Still no default, so still not configured -- setting the legacy variable
    # changed nothing, exactly as the remedy says.
    assert config.is_configured() is False
