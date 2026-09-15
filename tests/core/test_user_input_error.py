"""UserInputError's base class is load-bearing, so it is pinned by tests.

WHY THIS FILE EXISTS
--------------------
`class UserInputError(ValueError)` looks like an arbitrary choice and reads as
tidy-able: someone will eventually "simplify" it back to Exception, because
nothing at the definition site fails when they do. What fails is far away and
quiet -- every `except ValueError` in the codebase silently stops catching it,
and every `pytest.raises(ValueError)` in the suite starts failing for a reason
that points at the wrong file.

The base class is what makes converting a raise site SAFE. There are 238 bare
`raise ValueError` calls across this repo; each one converted to UserInputError
keeps working for its existing callers only because UserInputError IS a
ValueError. Reparent it and every one of those conversions becomes a breaking
change, retroactively.
"""

import logging

import pytest

from core.utils import UserInputError, handle_http_errors


def test_userinputerror_is_a_valueerror():
    """The pin. If this fails, someone reparented the exception."""
    assert issubclass(UserInputError, ValueError)


def test_existing_except_valueerror_still_catches_it():
    """The property that makes raise-site conversion non-breaking.

    Source code has 58 `except ValueError` handlers that predate any
    conversion; they must keep catching after a raise site is converted.
    """
    try:
        raise UserInputError("bad argument")
    except ValueError as exc:
        assert isinstance(exc, UserInputError)
    else:  # pragma: no cover - only reached if the base class regressed
        pytest.fail("UserInputError was not caught by `except ValueError`")


def test_existing_pytest_raises_valueerror_still_passes():
    """The suite has 106 `pytest.raises(ValueError)` assertions; a converted
    raise site must not require touching any of them."""
    with pytest.raises(ValueError):
        raise UserInputError("bad argument")


@pytest.mark.asyncio
async def test_decorator_still_takes_the_clean_branch(caplog):
    """The half that a subclass relationship could plausibly have broken.

    handle_http_errors matches except-clauses in order: `except UserInputError`
    sits ahead of the terminal `except Exception`. Being a ValueError must not
    divert it into the generic branch, which would log a full traceback at ERROR
    and re-raise a bare Exception reading "An unexpected error occurred" -- a
    user's bad argument reported as an internal fault.
    """

    @handle_http_errors("fake_tool", is_read_only=True)
    async def fake_tool(user_google_email: str = "u@example.com"):
        raise UserInputError("you passed the wrong thing")

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(UserInputError) as caught:
            await fake_tool()

    # Re-raised as ITSELF, not wrapped in a generic Exception.
    assert type(caught.value) is UserInputError
    assert "you passed the wrong thing" in str(caught.value)

    # Logged as input error at WARNING, not as an unexpected error at ERROR.
    assert any(
        rec.levelno == logging.WARNING
        and "Input error in fake_tool" in rec.getMessage()
        for rec in caplog.records
    ), (
        f"expected a WARNING 'Input error'; got {[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )
    assert not any(
        "An unexpected error occurred" in rec.getMessage() for rec in caplog.records
    ), "fell through to the generic branch"


@pytest.mark.asyncio
async def test_a_bare_valueerror_still_takes_the_generic_branch():
    """Negative control, and the reason the conversion work is worth doing.

    A plain ValueError must NOT be treated as user input -- otherwise this whole
    distinction is decorative and the tests above would pass no matter what the
    decorator did.
    """

    @handle_http_errors("fake_tool", is_read_only=True)
    async def fake_tool(user_google_email: str = "u@example.com"):
        raise ValueError("an internal invariant broke")

    with pytest.raises(Exception) as caught:
        await fake_tool()

    assert type(caught.value) is not UserInputError
    assert "An unexpected error occurred" in str(caught.value)
