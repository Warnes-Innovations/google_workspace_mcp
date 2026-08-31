"""Suite-wide safety nets for global state that outlives a single test.

The one thing guarded here is a *live event loop* escaping into the rest of the
session. auth.oauth_callback_server.MinimalOAuthServer.start() runs
``asyncio.run(uvicorn.Server.serve())`` in a daemon thread, and uvicorn's
``Server.main_loop`` awaits ``asyncio.sleep(0.1)`` forever. Any test that
afterwards patches the process-global ``asyncio.sleep`` -- a normal thing to do
when testing a retry backoff -- then also intercepts that foreign loop's ticks,
because ``asyncio.sleep`` is one module attribute shared by every loop in the
process. It corrupts whatever the patching test records, and, since such a
replacement typically returns without awaiting, it turns the foreign poll loop
into a busy spin.

That is not hypothetical: measured on this suite, a leaked server produced
>500,000 stray ``asyncio.sleep(0.1)`` calls from its own thread inside a 0.5s
window. It made tests/gmail/test_gmail_batch_retry.py::
test_message_retry_uses_three_backoffs fail in full-suite runs while passing in
every subset, because only a broad run reaches the test that starts the server.

The individual test that starts one is expected to prevent or undo it; this is
the backstop that keeps a miss there from becoming a session-wide hazard.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_leaked_oauth_callback_server():
    """Stop the module-level OAuth callback server after every test.

    A no-op (one lock acquisition and a None check) unless a test actually
    started one, so it is safe to run for the whole suite.
    """
    yield

    from auth.oauth_callback_server import cleanup_oauth_callback_server

    cleanup_oauth_callback_server()
