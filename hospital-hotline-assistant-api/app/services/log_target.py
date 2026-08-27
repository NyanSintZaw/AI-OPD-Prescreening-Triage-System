"""Where operational log lines should actually go.

The app configures no logging of its own. Under uvicorn that means a module
logger like ``logging.getLogger(__name__)`` has no handler anywhere in its
ancestry, so ``logger.info(...)`` is discarded outright — while
``logger.error(...)`` still appears, via logging's lastResort handler at
WARNING. That asymmetry is a trap: instrumentation looks like it works,
because the failures print, and the healthy path is silently invisible.

``operational_logger()`` returns a logger that prints at INFO in every
context we run in — under uvicorn, under pytest, and in a bare script.
"""

from __future__ import annotations

import logging

_FALLBACK_CONFIGURED = False


def operational_logger(module_logger: logging.Logger) -> logging.Logger:
    """Resolve a logger whose INFO records are actually emitted.

    Prefers ``uvicorn.error`` — the logger uvicorn writes its own startup
    lines through — so our output interleaves with the server's in one
    stream. Note ``hasHandlers()`` rather than ``handlers``: uvicorn attaches
    the handler to the parent ``uvicorn`` logger and lets ``uvicorn.error``
    propagate, so ``uvicorn.error.handlers`` is empty even though it prints.
    """
    global _FALLBACK_CONFIGURED

    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger.hasHandlers():
        return uvicorn_logger
    if module_logger.hasHandlers():
        return module_logger
    # A bare script or a test run with no logging configured: give the module
    # logger a handler once, rather than let logging drop the records.
    if not _FALLBACK_CONFIGURED:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        _FALLBACK_CONFIGURED = True
    return module_logger
