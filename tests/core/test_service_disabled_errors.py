"""Regression tests: a disabled Google API must never be reported as an auth problem.

Google returns HTTP 403 both for "you are not authorized" and for "this API is
switched off in your Cloud project". Only the first is fixable by
re-authenticating; advising re-auth for the second sends the user into a
pointless consent loop for a Google Cloud Console problem.
"""

import json
import os
import sys

import pytest
from googleapiclient.errors import HttpError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core.api_enablement import (  # noqa: E402
    get_activation_url,
    get_api_enablement_message,
    is_service_disabled_error,
)
from core.utils import handle_http_errors  # noqa: E402
from gtasks.tasks_tools import _format_reauth_message  # noqa: E402


ACTIVATION_URL = (
    "https://console.developers.google.com/apis/api/docs.googleapis.com/"
    "overview?project=262805602987"
)


class _FakeResponse:
    def __init__(self, status, reason="Forbidden"):
        self.status = status
        self.reason = reason


def _service_disabled_error(
    service="docs.googleapis.com", display="Google Docs", status=403
):
    """Build the exact payload Google returns for a disabled API.

    Note the shape: ``error.details`` (google.rpc.ErrorInfo, reason
    SERVICE_DISABLED) AND the legacy ``error.errors[]`` (reason
    accessNotConfigured) are both present. googleapiclient's
    ``HttpError._get_reason`` populates ``error_details`` from the first of
    ("detail", "details", "errors", "message") that exists, so it picks
    ``details`` and the string "accessNotConfigured" never reaches
    ``str(error)``.
    """
    activation_url = (
        f"https://console.developers.google.com/apis/api/{service}/"
        "overview?project=262805602987"
    )
    message = (
        f"{display} API has not been used in project 262805602987 before or it "
        f"is disabled. Enable it by visiting {activation_url} then retry. If you "
        "enabled this API recently, wait a few minutes for the action to "
        "propagate to our systems and retry."
    )
    content = json.dumps(
        {
            "error": {
                "code": status,
                "message": message,
                "errors": [
                    {
                        "message": message,
                        "domain": "usageLimits",
                        "reason": "accessNotConfigured",
                        "extendedHelp": activation_url,
                    }
                ],
                "status": "PERMISSION_DENIED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "SERVICE_DISABLED",
                        "domain": "googleapis.com",
                        "metadata": {
                            "service": service,
                            "consumer": "projects/262805602987",
                            "activationUrl": activation_url,
                        },
                    }
                ],
            }
        }
    ).encode("utf-8")
    return HttpError(_FakeResponse(status), content, uri="https://example.invalid/v1")


def _genuine_permission_error():
    """A real 403 authorization failure - re-auth advice is correct here."""
    content = json.dumps(
        {
            "error": {
                "code": 403,
                "message": "The caller does not have permission",
                "status": "PERMISSION_DENIED",
            }
        }
    ).encode("utf-8")
    return HttpError(_FakeResponse(403), content, uri="https://example.invalid/v1")


def test_service_disabled_reason_is_not_visible_in_str():
    """Guards the premise: the legacy reason string really is absent."""
    error = _service_disabled_error()
    assert "accessNotConfigured" not in str(error)
    assert "SERVICE_DISABLED" in str(error)


def test_is_service_disabled_error_detects_structured_reason():
    error = _service_disabled_error()
    assert is_service_disabled_error(str(error), error.error_details) is True


def test_is_service_disabled_error_text_fallback():
    """No structured details available - fall back to Google's message text."""
    assert (
        is_service_disabled_error(
            "Google Docs API has not been used in project 1 before or it is disabled.",
            None,
        )
        is True
    )


def test_is_service_disabled_error_false_for_genuine_permission_denied():
    error = _genuine_permission_error()
    assert is_service_disabled_error(str(error), error.error_details) is False


def test_get_activation_url_prefers_error_payload():
    error = _service_disabled_error()
    assert get_activation_url(error.error_details) == ACTIVATION_URL


def test_enablement_message_uses_googles_activation_url():
    error = _service_disabled_error()
    message = get_api_enablement_message(str(error), "docs", error.error_details)
    assert ACTIVATION_URL in message
    assert "262805602987" in message
    assert "start_google_auth" in message  # only as an explicit "do NOT call it"
    assert "do not call 'start_google_auth'" in message


@pytest.mark.asyncio
async def test_handle_http_errors_service_disabled_does_not_advise_reauth():
    """The defect: SERVICE_DISABLED was falling through to the 401/403 branch."""

    @handle_http_errors("get_doc_content", service_type="docs")
    async def _tool(user_google_email: str):
        raise _service_disabled_error()

    with pytest.raises(Exception) as excinfo:
        await _tool(user_google_email="user@example.com")

    message = str(excinfo.value)
    assert "You might need to re-authenticate" not in message
    assert "Try 'start_google_auth'" not in message
    assert "not enabled for your project" in message
    assert ACTIVATION_URL in message


@pytest.mark.asyncio
async def test_handle_http_errors_still_advises_reauth_on_real_403():
    @handle_http_errors("get_doc_content", service_type="docs")
    async def _tool(user_google_email: str):
        raise _genuine_permission_error()

    with pytest.raises(Exception) as excinfo:
        await _tool(user_google_email="user@example.com")

    assert "You might need to re-authenticate" in str(excinfo.value)


@pytest.mark.asyncio
async def test_handle_http_errors_still_advises_reauth_on_401():
    content = json.dumps(
        {"error": {"code": 401, "message": "Invalid Credentials"}}
    ).encode("utf-8")

    @handle_http_errors("get_doc_content", service_type="docs")
    async def _tool(user_google_email: str):
        raise HttpError(
            _FakeResponse(401, "Unauthorized"), content, uri="https://example.invalid/"
        )

    with pytest.raises(Exception) as excinfo:
        await _tool(user_google_email="user@example.com")

    assert "You might need to re-authenticate" in str(excinfo.value)


def test_tasks_reauth_message_service_disabled_does_not_advise_reauth():
    """Sibling site: gtasks._format_reauth_message had the same defect."""
    error = _service_disabled_error(service="tasks.googleapis.com", display="Tasks")
    message = _format_reauth_message(error, "user@example.com")

    assert "You might need to re-authenticate" not in message
    assert "Try 'start_google_auth'" not in message
    assert "not enabled for your project" in message
    assert "tasks.googleapis.com" in message


def test_tasks_reauth_message_still_advises_reauth_on_real_403():
    message = _format_reauth_message(_genuine_permission_error(), "user@example.com")
    assert "You might need to re-authenticate" in message
