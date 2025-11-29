"""Pytest configuration and fixtures for amodem_duplex tests."""

import pytest

from amodem_duplex.tests.utils import suppress_amodem_warnings


@pytest.fixture(autouse=True)
def _suppress_warnings():
    """Automatically suppress amodem warnings for all tests."""
    with suppress_amodem_warnings():
        yield
