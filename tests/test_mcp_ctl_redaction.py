"""`check-config` must not print credentials from the [env] block.

The guard unions two independent signals -- a key that names a credential, and
a value shaped like a known credential format. Each is tested ALONE, because a
union whose halves are only ever exercised together cannot be shown to need
both, and the whole point is that either one catches what the other misses.
"""

import io
from contextlib import redirect_stdout

import pytest

from mcp_ctl import REDACTED, WorkspaceMCPConfig, print_config_summary, redact_env_value


def _summary(env: dict[str, str], tmp_path) -> str:
    config = WorkspaceMCPConfig(
        command=["python", "main.py"],
        args=[],
        working_dir=tmp_path,
        pid_file=tmp_path / "x.pid",
        log_file=tmp_path / "x.log",
        env_file=None,
        env=env,
        start_timeout=10,
    )
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        print_config_summary(config)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Signal 1 alone: the KEY names a credential, the value looks unremarkable
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "ANTHROPIC_API_KEY",
        "SOME_TOKEN",
        "DB_PASSWORD",
        "MY_PRIVATE_THING",
        "AWS_SECRET_ACCESS_KEY",
        "SESSION_SIGNING_KEY",
        "auth_header",  # lower-case keys must match too
    ],
)
def test_key_signal_alone_redacts(key):
    # "plainvalue" matches no value pattern, so only the key signal can fire.
    assert redact_env_value(key, "plainvalue") == REDACTED


# --------------------------------------------------------------------------
# Signal 2 alone: the KEY is innocuous, the VALUE is a known credential format
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "GOCSPX-liveSecretValue123",
        "ya29.a0AfH6SMBexample",
        "AIza" + "B" * 35,
        "sk-ant-api03-notreal",
        "sk-proj-" + "a" * 24,
        "ghp_" + "b" * 36,
        "github_pat_11ABCDE",
        "-----BEGIN RSA PRIVATE KEY-----",
    ],
)
def test_value_signal_alone_redacts(value):
    # "HARMLESS_SETTING" matches no key marker, so only the value signal fires.
    assert redact_env_value("HARMLESS_SETTING", value) == REDACTED


# --------------------------------------------------------------------------
# The guard must not swallow ordinary configuration
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key, value",
    [
        ("WORKSPACE_MCP_PORT", "8000"),
        ("OAUTHLIB_INSECURE_TRANSPORT", "1"),
        ("GOOGLE_OAUTH_CLIENT_ID", "262805602987-abc.apps.googleusercontent.com"),
        ("PATH", "/usr/local/bin:/usr/bin"),
        ("LOG_LEVEL", "debug"),
        ("DESCRIPTION", "a token of appreciation"),  # value text, not a key marker
    ],
)
def test_ordinary_values_survive(key, value):
    assert redact_env_value(key, value) == value


def test_client_id_is_not_redacted():
    # The client_id is published in every authorization URL. Redacting it would
    # cost diagnosability for no benefit -- and a guard that over-redacts gets
    # switched off.
    key, value = (
        "GOOGLE_OAUTH_CLIENT_ID",
        "597015601632-baffk2c.apps.googleusercontent.com",
    )
    assert redact_env_value(key, value) == value


# --------------------------------------------------------------------------
# End to end through the real printer
# --------------------------------------------------------------------------


def test_check_config_output_contains_no_secret(tmp_path):
    secret = "GOCSPX-liveSecretValue123"
    anthropic = "sk-ant-api03-notreal"
    out = _summary(
        {
            "WORKSPACE_MCP_PORT": "8000",
            "GOOGLE_OAUTH_CLIENT_SECRET": secret,
            "ANTHROPIC_API_KEY": anthropic,
        },
        tmp_path,
    )

    assert secret not in out
    assert anthropic not in out
    # Engagement: the keys are still listed, so a reader can see WHAT is set
    # without seeing the value. Without this a guard that dropped the whole
    # block would pass the assertions above while destroying the output.
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in out
    assert "ANTHROPIC_API_KEY" in out
    assert out.count(REDACTED) == 2
    # And ordinary settings are untouched.
    assert "WORKSPACE_MCP_PORT=8000" in out


def test_summary_with_no_env_block_is_unchanged(tmp_path):
    out = _summary({}, tmp_path)
    assert "env:" not in out
    assert REDACTED not in out
