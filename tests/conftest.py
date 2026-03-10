"""Shared test fixtures for the Cross-Tenant Service Bus Subscriber tests."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _mock_configure_azure_monitor():
    """Prevent the OpenTelemetry SDK from initialising during unit tests.

    ``configure_azure_monitor()`` is called at module level in
    ``function_app.py``.  Every ``importlib.reload(fa)`` re-executes it, which
    would fail without ``APPLICATIONINSIGHTS_CONNECTION_STRING`` and produce
    unwanted side-effects.  This autouse fixture patches it for every test.
    """
    with patch("azure.monitor.opentelemetry.configure_azure_monitor"):
        yield
