"""Gating for tests that call the real Google APIs.

These are OPT-IN and skip by default, so a contributor with no credentials —
and CI on a fork, which cannot have them — sees them skipped rather than
failed. A test that fails for lack of a secret trains people to ignore red.

Enable with BOTH:

    WORKSPACE_MCP_LIVE_TESTS=1
    a cached credential file under ~/.google_workspace_mcp/credentials/

Two conditions, not one, because the env var alone would turn "I opted in" into
a confusing auth error, and credentials alone would make every developer who
has ever run the server start hitting the live API from a bare `pytest`.

WHAT THESE ARE FOR, and why mocks are not enough. A mocked Drive answers
whatever the mock was told to answer, so a mock-only suite proves we SEND the
request we intended and is silent on whether Google understands it. That gap
has already produced a wrong conclusion in this project: the Drive query-escape
bypass was only ever confirmed by hitting the live API with a control, and a
schema assumption that "works here unchanged" turned out to be false against
the real service, which falls back rather than raising.

WHAT THEY MUST NOT DO: no writes. These run against a real person's Drive.
Read-only calls only — no create, update, move, trash or permission change.
"""

import json
import os
import pathlib

import pytest

CREDENTIALS_DIR = pathlib.Path.home() / ".google_workspace_mcp" / "credentials"
OPT_IN_VAR = "WORKSPACE_MCP_LIVE_TESTS"


def _credential_files():
    if not CREDENTIALS_DIR.is_dir():
        return []
    # oauth_states.json is bookkeeping, not an account credential.
    return sorted(
        p for p in CREDENTIALS_DIR.glob("*.json") if p.name != "oauth_states.json"
    )


def pytest_collection_modifyitems(config, items):
    """Skip everything in tests/live/ unless explicitly enabled."""
    if os.getenv(OPT_IN_VAR, "").strip() not in {"1", "true", "yes"}:
        skip = pytest.mark.skip(reason=f"live API tests are opt-in: set {OPT_IN_VAR}=1")
    elif not _credential_files():
        skip = pytest.mark.skip(
            reason=f"{OPT_IN_VAR} is set but no credentials in {CREDENTIALS_DIR}"
        )
    else:
        return
    for item in items:
        if pathlib.Path(str(item.fspath)).parent.name == "live":
            item.add_marker(skip)


@pytest.fixture(scope="session")
def live_drive_service():
    """A real, read-only Drive v3 client built from a cached credential."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    files = _credential_files()
    if not files:
        pytest.skip(f"no credential files in {CREDENTIALS_DIR}")

    creds = Credentials.from_authorized_user_info(json.loads(files[0].read_text()))
    return build("drive", "v3", credentials=creds, cache_discovery=False)
