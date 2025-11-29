"""Miscellaneous utilities for amodem_duplex."""

import warnings
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def suppress_amodem_warnings() -> Iterator[None]:
    """Suppress deprecation warnings from the amodem package."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"tostring\(\) is deprecated.*",
            category=DeprecationWarning,
        )
        yield
