"""Any workflow holding elevated permissions must SHA-pin every action it uses.

A floating tag can be force-moved and a branch ref is *expected* to move, so
either lets the action's maintainer -- or anyone who compromises them -- inject
code into a workflow that holds real credentials.

This asserts the property from the file rather than from memory, because the
manual survey that produced this change UNDERCOUNTED: it grepped `^\\s*uses:`
and missed the `- uses:` list-item form, reporting 2 refs in ruff.yml where
there are 6. That is the third time in one session a pattern encoded an
assumption about formatting rather than about the thing being checked.
"""

import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

# Permissions that make a workflow worth attacking: it can mint an OIDC token,
# publish a package, or write to the repository.
ELEVATED = ("id-token", "packages", "contents")

SHA40 = re.compile(r"^[0-9a-f]{40}$")
USES = re.compile(r"uses:\s*([^\s#]+)")


def _workflows():
    return sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))


def _has_elevated_permission(text: str) -> bool:
    """True if any `<perm>: write` appears, at workflow or job level.

    Read textually on purpose: permissions can sit at either level, and a YAML
    walk that looked only at the top-level `permissions:` key would miss the
    job-level block -- which is exactly where docker-publish.yml declares them.
    """
    return any(re.search(rf"{p}:\s*write", text) for p in ELEVATED)


def _refs(text: str):
    for lineno, line in enumerate(text.splitlines(), 1):
        m = USES.search(line)
        if m:
            repo, _, rev = m.group(1).partition("@")
            yield lineno, repo, rev


def test_workflow_directory_is_not_empty():
    """Negative control: an empty census must not pass vacuously."""
    assert _workflows(), "no workflows found; this test is checking nothing"


def test_the_scanner_finds_action_references():
    """Negative control: the ref parser must actually parse refs.

    Guards the `- uses:` list-item form specifically, since missing it is what
    made the manual survey undercount.
    """
    found = [
        (p.name, repo)
        for p in _workflows()
        for _, repo, _ in _refs(p.read_text(encoding="utf-8"))
    ]
    assert found, "no action references parsed; the scanner is broken"
    assert any(
        line.strip().startswith("- uses:")
        for p in _workflows()
        for line in p.read_text(encoding="utf-8").splitlines()
    ), "no list-item `- uses:` form present to exercise the parser against"


@pytest.mark.parametrize("path", _workflows(), ids=lambda p: p.name)
def test_workflow_yaml_is_valid(path):
    assert yaml.safe_load(path.read_text(encoding="utf-8")) is not None


@pytest.mark.parametrize("path", _workflows(), ids=lambda p: p.name)
def test_elevated_workflows_pin_every_action_to_a_sha(path):
    """The rule: elevated permissions require a 40-hex commit SHA, never a tag.

    If this fails on a NEW action, resolve its tag to a commit SHA and pin it,
    keeping the version as a trailing comment so Dependabot can still bump it.
    Do not relax the assertion.
    """
    text = path.read_text(encoding="utf-8")
    if not _has_elevated_permission(text):
        pytest.skip(f"{path.name} holds no elevated permission")
    unpinned = [
        f"{path.name}:{lineno} {repo}@{rev}"
        for lineno, repo, rev in _refs(text)
        if not SHA40.match(rev)
    ]
    assert not unpinned, (
        f"elevated workflow uses a floating ref: {unpinned}. "
        f"Pin to a 40-char commit SHA."
    )


def test_at_least_one_workflow_is_elevated():
    """Negative control for the skip above.

    If the elevation detector broke, every workflow would skip and the suite
    would be green while checking nothing.
    """
    elevated = [
        p.name
        for p in _workflows()
        if _has_elevated_permission(p.read_text(encoding="utf-8"))
    ]
    assert elevated, "no workflow detected as elevated; the detector is broken"
