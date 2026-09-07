import re
from typing import Any, Dict, Iterator, Optional, Tuple


API_ENABLEMENT_LINKS: Dict[str, str] = {
    "calendar-json.googleapis.com": "https://console.cloud.google.com/flows/enableapi?apiid=calendar-json.googleapis.com",
    "drive.googleapis.com": "https://console.cloud.google.com/flows/enableapi?apiid=drive.googleapis.com",
    "gmail.googleapis.com": "https://console.cloud.google.com/flows/enableapi?apiid=gmail.googleapis.com",
    "docs.googleapis.com": "https://console.cloud.google.com/flows/enableapi?apiid=docs.googleapis.com",
    "sheets.googleapis.com": "https://console.cloud.google.com/flows/enableapi?apiid=sheets.googleapis.com",
    "slides.googleapis.com": "https://console.cloud.google.com/flows/enableapi?apiid=slides.googleapis.com",
    "forms.googleapis.com": "https://console.cloud.google.com/flows/enableapi?apiid=forms.googleapis.com",
    "tasks.googleapis.com": "https://console.cloud.google.com/flows/enableapi?apiid=tasks.googleapis.com",
    "chat.googleapis.com": "https://console.cloud.google.com/flows/enableapi?apiid=chat.googleapis.com",
    "customsearch.googleapis.com": "https://console.cloud.google.com/flows/enableapi?apiid=customsearch.googleapis.com",
}


SERVICE_NAME_TO_API: Dict[str, str] = {
    "Google Calendar": "calendar-json.googleapis.com",
    "Google Drive": "drive.googleapis.com",
    "Gmail": "gmail.googleapis.com",
    "Google Docs": "docs.googleapis.com",
    "Google Sheets": "sheets.googleapis.com",
    "Google Slides": "slides.googleapis.com",
    "Google Forms": "forms.googleapis.com",
    "Google Tasks": "tasks.googleapis.com",
    "Google Chat": "chat.googleapis.com",
    "Google Custom Search": "customsearch.googleapis.com",
}


INTERNAL_SERVICE_TO_API: Dict[str, str] = {
    "calendar": "calendar-json.googleapis.com",
    "drive": "drive.googleapis.com",
    "gmail": "gmail.googleapis.com",
    "docs": "docs.googleapis.com",
    "sheets": "sheets.googleapis.com",
    "slides": "slides.googleapis.com",
    "forms": "forms.googleapis.com",
    "tasks": "tasks.googleapis.com",
    "chat": "chat.googleapis.com",
    "customsearch": "customsearch.googleapis.com",
    "search": "customsearch.googleapis.com",
}


# Google reports "this API is not turned on for your Cloud project" in two
# overlapping shapes on the SAME HTTP 403 response:
#   * the modern google.rpc.ErrorInfo entry under ``error.details`` with
#     ``reason == "SERVICE_DISABLED"``, and
#   * the legacy ``error.errors[]`` entry with ``reason == "accessNotConfigured"``.
# googleapiclient's HttpError._get_reason() populates ``error_details`` from the
# FIRST key it finds among ("detail", "details", "errors", "message"), so when
# ``details`` is present the legacy ``accessNotConfigured`` string never appears
# in ``str(error)`` at all. Matching on that string alone therefore misses the
# common case and the error falls through to the generic 401/403 branch, which
# tells the user to re-authenticate - advice that cannot possibly fix a disabled
# API and sends them into a pointless consent loop.
SERVICE_DISABLED_REASONS = frozenset({"SERVICE_DISABLED", "accessNotConfigured"})

# Text fallbacks for payloads where no structured reason survives, matched
# case-insensitively against str(error).
SERVICE_DISABLED_TEXT_MARKERS: Tuple[str, ...] = (
    "accessnotconfigured",
    "service_disabled",
    "has not been used in project",
    "or it is disabled",
)


def _iter_detail_dicts(structured_details: Any) -> Iterator[Dict[str, Any]]:
    """Yield dict entries from an ``HttpError.error_details`` payload.

    ``error_details`` may be a list of error/detail dicts, a single dict, or a
    bare string; anything that is not a dict is skipped rather than raising.
    """
    if isinstance(structured_details, dict):
        yield structured_details
    elif isinstance(structured_details, (list, tuple)):
        for entry in structured_details:
            if isinstance(entry, dict):
                yield entry


def extract_service_disabled_details(
    structured_details: Any,
) -> Optional[Dict[str, Any]]:
    """Return the detail entry whose ``reason`` marks the API as disabled."""
    for entry in _iter_detail_dicts(structured_details):
        if entry.get("reason") in SERVICE_DISABLED_REASONS:
            return entry
    return None


def get_activation_url(structured_details: Any) -> Optional[str]:
    """Extract Google's own API activation URL from an error payload.

    Prefers ``metadata.activationUrl`` (google.rpc.ErrorInfo) and falls back to
    the legacy ``extendedHelp`` link on an ``accessNotConfigured`` entry.
    """
    for entry in _iter_detail_dicts(structured_details):
        metadata = entry.get("metadata")
        if isinstance(metadata, dict) and metadata.get("activationUrl"):
            return metadata["activationUrl"]
    for entry in _iter_detail_dicts(structured_details):
        if entry.get("reason") in SERVICE_DISABLED_REASONS and entry.get(
            "extendedHelp"
        ):
            return entry["extendedHelp"]
    return None


def is_service_disabled_error(
    error_details: str, structured_details: Any = None
) -> bool:
    """Is this 403 a disabled-API (project config) problem rather than an auth problem?

    Checks the structured ``reason`` field first and falls back to matching
    Google's message text, so a payload that loses either representation is
    still classified correctly.
    """
    if extract_service_disabled_details(structured_details) is not None:
        return True

    haystack = (error_details or "").lower()
    return any(marker in haystack for marker in SERVICE_DISABLED_TEXT_MARKERS)


def extract_api_info_from_error(
    error_details: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract API service and project ID from error details.

    Returns:
        Tuple of (api_service, project_id) or (None, None) if not found
    """
    api_pattern = r"https://console\.developers\.google\.com/apis/api/([^/]+)/overview"
    project_pattern = r"project[=\s]+([a-zA-Z0-9-]+)"

    api_match = re.search(api_pattern, error_details)
    project_match = re.search(project_pattern, error_details)

    api_service = api_match.group(1) if api_match else None
    project_id = project_match.group(1) if project_match else None

    return api_service, project_id


def get_api_enablement_message(
    error_details: str,
    service_type: Optional[str] = None,
    structured_details: Any = None,
) -> str:
    """
    Generate a helpful error message with direct API enablement link.

    Args:
        error_details: The error details string from the HttpError
        service_type: Optional service type (e.g., "calendar", "gmail", or "Google Calendar")
        structured_details: Optional ``HttpError.error_details`` payload, used to
            recover the API name, project id, and Google's own activation URL.

    Returns:
        Formatted error message with enablement link, or "" if the API could not
        be identified.
    """
    api_service, project_id = extract_api_info_from_error(error_details)

    disabled_detail = extract_service_disabled_details(structured_details)
    if disabled_detail:
        metadata = disabled_detail.get("metadata")
        if isinstance(metadata, dict):
            api_service = api_service or metadata.get("service")
            consumer = metadata.get("consumer") or ""
            if not project_id and consumer.startswith("projects/"):
                project_id = consumer.split("/", 1)[1] or None

    if not api_service and service_type:
        # Check internal service names first (e.g., "calendar", "gmail")
        api_service = INTERNAL_SERVICE_TO_API.get(service_type)
        if not api_service:
            # Check display names (e.g., "Google Calendar")
            api_service = SERVICE_NAME_TO_API.get(service_type)

    # Prefer the activation URL Google itself put in the error payload; it is
    # already scoped to the offending project.
    enable_link = get_activation_url(structured_details) or API_ENABLEMENT_LINKS.get(
        api_service or ""
    )

    if enable_link:
        service_display_name = next(
            (name for name, api in SERVICE_NAME_TO_API.items() if api == api_service),
            api_service or "The required Google",
        )

        message = (
            f"{service_display_name} API is not enabled for your project"
            f"{f' ({project_id})' if project_id else ''}.\n\n"
            f"Enable it here: {enable_link}\n\n"
            f"After enabling, wait 1-2 minutes for the change to propagate, then try again.\n\n"
            f"This is a Google Cloud project configuration problem, NOT an authentication "
            f"problem. Re-authenticating will not fix it - do not call 'start_google_auth'.\n"
            f"IMPORTANT - LLM: share the link provided as a clickable hyperlink and instruct the user to enable the required API."
        )

        return message

    return ""
