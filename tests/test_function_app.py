"""
Unit tests for the Cross-Tenant Service Bus Subscriber function.

These tests verify the core logic without requiring real Azure credentials
or connections.  All external dependencies are mocked.
"""

import json
import os
import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

# ── Make src/function_app importable ─────────────────────────────────────────
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "src", "function_app"),
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_sb_message(
    body: bytes = b'{"event": "test"}',
    message_id: str = "msg-001",
    content_type: str = "application/json",
):
    """Create a mock func.ServiceBusMessage."""
    msg = MagicMock()
    msg.get_body.return_value = body
    msg.message_id = message_id
    msg.content_type = content_type
    msg.subject = "test-subject"
    msg.correlation_id = "corr-001"
    msg.application_properties = {"key": "value"}
    msg.enqueued_time_utc = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
    return msg


def _base_env(extra: dict | None = None) -> dict:
    """Return a minimal set of required environment variables."""
    env = {
        "SERVICE_BUS_CONNECTION__fullyQualifiedNamespace": "test-ns.servicebus.windows.net",
        "SERVICE_BUS_CONNECTION__credential": "managedidentityasfederatedidentity",
        "SERVICE_BUS_CONNECTION__azureCloud": "public",
        "SERVICE_BUS_CONNECTION__clientId": "app-reg-client-id-in-tenant-b",
        "SERVICE_BUS_CONNECTION__tenantId": "tenant-b-id",
        "SERVICE_BUS_CONNECTION__managedIdentityClientId": "uami-client-id",
        "CROSS_TENANT_TOPIC_NAME": "test-topic",
        "CROSS_TENANT_SUBSCRIPTION_NAME": "test-sub",
        "USER_ASSIGNED_MI_CLIENT_ID": "uami-client-id",
        "STORAGE_ACCOUNT_NAME": "teststorage",
        "STORAGE_CONTAINER_NAME": "sb-messages",
    }
    if extra:
        env.update(extra)
    return env


# ── Tests: _require_env ───────────────────────────────────────────────────────

class TestRequireEnv:
    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "hello")
        import importlib
        import function_app as fa
        importlib.reload(fa)
        assert fa._require_env("MY_VAR") == "hello"

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        import function_app as fa
        with pytest.raises(EnvironmentError, match="MISSING_VAR"):
            fa._require_env("MISSING_VAR")


# ── Tests: _opt_env ───────────────────────────────────────────────────────────

class TestOptEnv:
    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("OPT_VAR", "custom")
        import function_app as fa
        assert fa._opt_env("OPT_VAR", "default") == "custom"

    def test_returns_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("OPT_VAR", raising=False)
        import function_app as fa
        assert fa._opt_env("OPT_VAR", "default") == "default"


# ── Tests: _write_message_to_blob ─────────────────────────────────────────────

class TestWriteMessageToBlob:
    def test_writes_blob_with_correct_structure(self):
        import function_app as fa

        mock_blob_client = MagicMock()
        mock_bsc = MagicMock()
        mock_bsc.get_blob_client.return_value = mock_blob_client

        msg = _make_sb_message(body=b'{"hello": "world"}', message_id="abc-123")

        blob_name = fa._write_message_to_blob(mock_bsc, "test-container", msg)

        # Verify blob name format YYYY/MM/DD/<message-id>.json
        assert blob_name.endswith("abc-123.json")
        parts = blob_name.split("/")
        assert len(parts) == 4  # year/month/day/filename

        # Verify upload was called once
        mock_blob_client.upload_blob.assert_called_once()
        upload_args = mock_blob_client.upload_blob.call_args
        payload = json.loads(upload_args[0][0].decode("utf-8"))

        assert payload["messageId"] == "abc-123"
        assert payload["body"] == '{"hello": "world"}'
        assert payload["subject"] == "test-subject"
        assert payload["correlationId"] == "corr-001"

    def test_handles_missing_message_id(self):
        import function_app as fa

        mock_blob_client = MagicMock()
        mock_bsc = MagicMock()
        mock_bsc.get_blob_client.return_value = mock_blob_client

        msg = _make_sb_message()
        msg.message_id = None

        blob_name = fa._write_message_to_blob(mock_bsc, "container", msg)

        # Should generate a UUID-based name
        assert blob_name.endswith(".json")

    def test_overwrite_true(self):
        import function_app as fa

        mock_blob_client = MagicMock()
        mock_bsc = MagicMock()
        mock_bsc.get_blob_client.return_value = mock_blob_client

        msg = _make_sb_message()
        fa._write_message_to_blob(mock_bsc, "container", msg)

        mock_blob_client.upload_blob.assert_called_once()
        kwargs = mock_blob_client.upload_blob.call_args[1]
        assert kwargs.get("overwrite") is True


# ── Tests: service_bus_subscriber (integration-style, fully mocked) ───────────

class TestServiceBusSubscriber:
    """Tests for the main Service Bus–triggered function."""

    def _run_subscriber(self, message, monkeypatch, env_extra=None):
        """Helper: patch all external deps and invoke the subscriber."""
        import importlib
        import function_app as fa
        importlib.reload(fa)

        env = _base_env(env_extra)
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        mock_blob_client = MagicMock()
        mock_bsc_instance = MagicMock()
        mock_bsc_instance.get_blob_client.return_value = mock_blob_client

        with (
            patch.object(fa, "BlobServiceClient", return_value=mock_bsc_instance),
            patch.object(fa, "ManagedIdentityCredential"),
        ):
            fa.service_bus_subscriber(message)

        return mock_bsc_instance, mock_blob_client

    def test_happy_path_writes_blob(self, monkeypatch):
        """A single message should result in exactly one blob upload."""
        msg = _make_sb_message()
        _, mock_blob_client = self._run_subscriber(msg, monkeypatch)

        mock_blob_client.upload_blob.assert_called_once()

    def test_blob_write_failure_raises_exception(self, monkeypatch):
        """When blob write fails the subscriber must re-raise so the runtime abandons the message."""
        import importlib
        import function_app as fa
        importlib.reload(fa)

        env = _base_env()
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        msg = _make_sb_message()

        mock_blob_client = MagicMock()
        mock_blob_client.upload_blob.side_effect = RuntimeError("disk full")
        mock_bsc_instance = MagicMock()
        mock_bsc_instance.get_blob_client.return_value = mock_blob_client

        with (
            patch.object(fa, "BlobServiceClient", return_value=mock_bsc_instance),
            patch.object(fa, "ManagedIdentityCredential"),
        ):
            with pytest.raises(RuntimeError, match="disk full"):
                fa.service_bus_subscriber(msg)

    def test_missing_storage_env_var_raises(self, monkeypatch):
        """Missing STORAGE_ACCOUNT_NAME must raise EnvironmentError."""
        import importlib
        import function_app as fa
        importlib.reload(fa)

        env = _base_env()
        env.pop("STORAGE_ACCOUNT_NAME", None)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("STORAGE_ACCOUNT_NAME", raising=False)

        msg = _make_sb_message()

        with (
            patch.object(fa, "BlobServiceClient"),
            patch.object(fa, "ManagedIdentityCredential"),
        ):
            with pytest.raises(EnvironmentError, match="STORAGE_ACCOUNT_NAME"):
                fa.service_bus_subscriber(msg)
