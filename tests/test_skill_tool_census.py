"""Every registered tool must be reachable from the skill's router.

WHY THIS IS A RUNTIME CENSUS AND NOT A GREP
-------------------------------------------
Two earlier attempts at this question got a clean-looking wrong answer:

1. A regex over ``@server.tool`` decorators. Regex sweeps have produced false
   clean results in this repo repeatedly; they are not used here.

2. An AST scan for functions carrying a ``.tool`` decorator. That one is
   structurally sound and still missed six tools, because
   ``core.comments.create_comment_tools`` is a FACTORY: it builds each tool's
   name with an f-string (``f"list_{app_name}_comments"``), so the names in
   source are ``list_comments`` / ``manage_comment`` and the registered names
   -- ``list_document_comments``, ``manage_spreadsheet_comment``, ... -- exist
   only at runtime. No static analysis can see them.

So the tool list comes from the server itself, after importing the same
service modules ``main`` imports. Reading the source tells you what the author
meant to register; only running it tells you what is registered.

WHAT A FAILURE HERE MEANS
-------------------------
A tool absent from ``SKILL.md`` works fine -- it is simply undiscoverable to an
agent reading the skill, which is the only way most callers find tools at all.
The fix is to add a router row and a reference entry, not to relax this test.
"""

import json
import os
import subprocess
import sys
import tempfile
import re
from pathlib import Path

import pytest

SKILL_DIR = (
    Path(__file__).resolve().parent.parent / "skills" / "managing-google-workspace"
)
SKILL_MD = SKILL_DIR / "SKILL.md"


# Run in a SUBPROCESS, not in-process. The server is a module-level singleton
# and the rest of the suite mutates it; importing it here after those tests have
# run reported 9 tools instead of 123, which would have made every coverage
# assertion below pass vacuously. A subprocess also measures a freshly started
# server, which is the thing we actually care about.
#
# The result comes back through a FILE, not stdout: importing `main` redirects
# stdout, so a subprocess that writes there exits 0 with nothing captured --
# a silent empty result, which is the worst possible failure for a census.
_CENSUS_SCRIPT = """
import asyncio, json, os
from importlib import import_module
import main
from core.server import server
for module_path in main.SERVICE_MODULES.values():
    import_module(module_path)
tools = asyncio.run(server.list_tools())
with open(os.environ["CENSUS_OUT"], "w") as fh:
    json.dump(sorted(t.name for t in tools), fh)
"""


def _registered_tool_names():
    """Ask a freshly started server what it registered."""
    repo_root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "tools.json"
        proc = subprocess.run(
            [sys.executable, "-c", _CENSUS_SCRIPT],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            env={
                **os.environ,
                # Never used to authenticate; import refuses without them present.
                "GOOGLE_OAUTH_CLIENT_ID": "census-placeholder",
                "GOOGLE_OAUTH_CLIENT_SECRET": "census-placeholder",
                "CENSUS_OUT": str(out),
            },
        )
        assert proc.returncode == 0, (
            f"tool census subprocess failed ({proc.returncode}):\n{proc.stderr[-2000:]}"
        )
        assert out.exists(), (
            "tool census subprocess exited 0 but wrote no result file; "
            f"stderr:\n{proc.stderr[-2000:]}"
        )
        return json.loads(out.read_text())


def _names_in(text):
    """Tool names mentioned in a markdown file, matched whole."""
    return set(re.findall(r"\b[a-z][a-z0-9_]{3,}\b", text))


@pytest.fixture(scope="module")
def tool_names():
    names = _registered_tool_names()
    # Control: the census must find tools we know exist. If this list ever
    # empties or shrinks to a handful, the import path broke and every
    # coverage assertion below would pass vacuously.
    assert len(names) > 100, (
        f"census found only {len(names)} tools; import path likely broken"
    )
    for known in ("search_drive_files", "send_gmail_message", "list_calendars"):
        assert known in names, f"census missed {known}; it is registered"
    # Control: a name built by the comment factory, invisible to static scans.
    assert "list_document_comments" in names
    return names


def test_every_registered_tool_is_in_the_skill_router(tool_names):
    """SKILL.md routes a request to a reference file; a tool it never names
    cannot be routed to."""
    routed = _names_in(SKILL_MD.read_text(encoding="utf-8"))
    missing = [name for name in tool_names if name not in routed]
    assert not missing, (
        "registered but absent from SKILL.md, so undiscoverable to an agent "
        f"reading the skill: {missing}"
    )


def test_every_registered_tool_has_a_reference_entry(tool_names):
    """A router row pointing at a page that does not describe the tool just
    moves the dead end one hop further along.

    This looks for an actual `### tool_name` HEADING, not a mention. An earlier
    version accepted any occurrence of the name and passed with a tool's entry
    deleted, because the name still appeared in the page's Contents list and in
    a neighbouring tool's prose -- it was asserting something true for the
    wrong reason.
    """
    documented = set()
    for ref in (SKILL_DIR / "references").glob("*.md"):
        documented |= set(
            re.findall(
                r"^#{2,4}\s+`?([a-z][a-z0-9_]+)`?\s*$",
                ref.read_text(encoding="utf-8"),
                re.M,
            )
        )
    missing = [name for name in tool_names if name not in documented]
    assert not missing, f"no `### <name>` entry in any reference file: {missing}"


def test_census_would_notice_a_missing_tool(tool_names):
    """Negative control. A guard never seen failing is decoration -- this
    proves the coverage checks above can actually fail, by asking the same
    question about a tool name that is deliberately not documented anywhere."""
    routed = _names_in(SKILL_MD.read_text(encoding="utf-8"))
    fabricated = "manage_nonexistent_widget"
    assert fabricated not in tool_names, "pick a name that is genuinely not a tool"
    assert fabricated not in routed, "pick a name that is genuinely undocumented"
