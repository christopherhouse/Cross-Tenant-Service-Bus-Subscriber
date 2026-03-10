"""
Unit tests for the Cross-Tenant Service Bus Subscriber function.

These tests verify the core logic without requiring real Azure credentials
or connections.  All external dependencies are mocked.
"""

import json
import os
import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, call, patch

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
    """Create a mock Service Bus message."""
    msg = MagicMock()
    msg.body = body
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
        "CROSS_TENANT_SERVICE_BUS_NAMESPACE": "test-ns.servicebus.windows.net",
        "CROSS_TENANT_TOPIC_NAME": "test-topic",
        "CROSS_TENANT_SUBSCRIPTION_NAME": "test-sub",
        "CROSS_TENANT_TENANT_ID": "tenant-b-id",
        "CROSS_TENANT_APP_CLIENT_ID": "app-client-id",
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

    def test_handles_byte_generator_body(self):
        import function_app as fa

        mock_blob_client = MagicMock()
        mock_bsc = MagicMock()
        mock_bsc.get_blob_client.return_value = mock_blob_client

        # Simulate a generator body (as returned by azure-servicebus)
        msg = _make_sb_message()
        msg.body = iter([b'{"gen": ', b'"body"}'])

        fa._write_message_to_blob(mock_bsc, "container", msg)

        upload_data = mock_blob_client.upload_blob.call_args[0][0]
        payload = json.loads(upload_data)
        assert payload["body"] == '{"gen": "body"}'

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


# ── Tests: service_bus_poller (integration-style, fully mocked) ───────────────

class TestServiceBusPoller:
    """Tests for the main timer-triggered function."""

    def _run_poller(self, messages, monkeypatch, env_extra=None):
        """Helper: patch all external deps and invoke the poller."""
        import importlib
        import function_app as fa
        importlib.reload(fa)

        env = _base_env(env_extra)
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        # Build mock Service Bus hierarchy
        mock_receiver = MagicMock()
        mock_receiver.receive_messages.return_value = messages
        mock_receiver.__enter__ = MagicMock(return_value=mock_receiver)
        mock_receiver.__exit__ = MagicMock(return_value=False)

        mock_sb_client = MagicMock()
        mock_sb_client.get_subscription_receiver.return_value = mock_receiver
        mock_sb_client.__enter__ = MagicMock(return_value=mock_sb_client)
        mock_sb_client.__exit__ = MagicMock(return_value=False)

        mock_blob_client = MagicMock()
        mock_bsc_instance = MagicMock()
        mock_bsc_instance.get_blob_client.return_value = mock_blob_client

        timer = MagicMock()
        timer.past_due = False

        with (
            patch.object(fa, "ServiceBusClient", return_value=mock_sb_client),
            patch.object(fa, "BlobServiceClient", return_value=mock_bsc_instance),
            patch.object(fa, "ManagedIdentityCredential"),
            patch.object(fa, "ClientAssertionCredential"),
        ):
            fa.service_bus_poller(timer)

        return mock_receiver, mock_bsc_instance, mock_blob_client

    def test_happy_path_single_message(self, monkeypatch):
        msg = _make_sb_message()
        receiver, _, _ = self._run_poller([msg], monkeypatch)

        receiver.complete_message.assert_called_once_with(msg)
        receiver.abandon_message.assert_not_called()

    def test_happy_path_multiple_messages(self, monkeypatch):
        messages = [_make_sb_message(message_id=f"msg-{i}") for i in range(3)]
        receiver, _, _ = self._run_poller(messages, monkeypatch)

        assert receiver.complete_message.call_count == 3
        receiver.abandon_message.assert_not_called()

    def test_empty_batch_no_errors(self, monkeypatch):
        receiver, _, _ = self._run_poller([], monkeypatch)

        receiver.complete_message.assert_not_called()
        receiver.abandon_message.assert_not_called()

    def test_blob_write_failure_abandons_message(self, monkeypatch):
        """When blob write fails the message should be abandoned, not completed."""
        import importlib
        import function_app as fa
        importlib.reload(fa)

        env = _base_env()
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        msg = _make_sb_message()

        mock_receiver = MagicMock()
        mock_receiver.receive_messages.return_value = [msg]
        mock_receiver.__enter__ = MagicMock(return_value=mock_receiver)
        mock_receiver.__exit__ = MagicMock(return_value=False)

        mock_sb_client = MagicMock()
        mock_sb_client.get_subscription_receiver.return_value = mock_receiver
        mock_sb_client.__enter__ = MagicMock(return_value=mock_sb_client)
        mock_sb_client.__exit__ = MagicMock(return_value=False)

        # Make blob upload raise
        mock_blob_client = MagicMock()
        mock_blob_client.upload_blob.side_effect = RuntimeError("disk full")
        mock_bsc_instance = MagicMock()
        mock_bsc_instance.get_blob_client.return_value = mock_blob_client

        timer = MagicMock()
        timer.past_due = False

        with (
            patch.object(fa, "ServiceBusClient", return_value=mock_sb_client),
            patch.object(fa, "BlobServiceClient", return_value=mock_bsc_instance),
            patch.object(fa, "ManagedIdentityCredential"),
            patch.object(fa, "ClientAssertionCredential"),
        ):
            fa.service_bus_poller(timer)

        mock_receiver.abandon_message.assert_called_once_with(msg)
        mock_receiver.complete_message.assert_not_called()

    def test_past_due_timer_still_processes(self, monkeypatch):
        """A past-due timer should still process messages (just log a warning)."""
        import importlib
        import function_app as fa
        importlib.reload(fa)

        env = _base_env()
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        msg = _make_sb_message()

        mock_receiver = MagicMock()
        mock_receiver.receive_messages.return_value = [msg]
        mock_receiver.__enter__ = MagicMock(return_value=mock_receiver)
        mock_receiver.__exit__ = MagicMock(return_value=False)

        mock_sb_client = MagicMock()
        mock_sb_client.get_subscription_receiver.return_value = mock_receiver
        mock_sb_client.__enter__ = MagicMock(return_value=mock_sb_client)
        mock_sb_client.__exit__ = MagicMock(return_value=False)

        mock_blob_client = MagicMock()
        mock_bsc_instance = MagicMock()
        mock_bsc_instance.get_blob_client.return_value = mock_blob_client

        timer = MagicMock()
        timer.past_due = True

        with (
            patch.object(fa, "ServiceBusClient", return_value=mock_sb_client),
            patch.object(fa, "BlobServiceClient", return_value=mock_bsc_instance),
            patch.object(fa, "ManagedIdentityCredential"),
            patch.object(fa, "ClientAssertionCredential"),
        ):
            fa.service_bus_poller(timer)

        mock_receiver.complete_message.assert_called_once_with(msg)

    def test_mixed_success_and_failure(self, monkeypatch):
        """First message succeeds, second fails → first completed, second abandoned."""
        import importlib
        import function_app as fa
        importlib.reload(fa)

        env = _base_env()
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        msg_ok = _make_sb_message(message_id="ok-msg")
        msg_fail = _make_sb_message(message_id="fail-msg")

        mock_receiver = MagicMock()
        mock_receiver.receive_messages.return_value = [msg_ok, msg_fail]
        mock_receiver.__enter__ = MagicMock(return_value=mock_receiver)
        mock_receiver.__exit__ = MagicMock(return_value=False)

        mock_sb_client = MagicMock()
        mock_sb_client.get_subscription_receiver.return_value = mock_receiver
        mock_sb_client.__enter__ = MagicMock(return_value=mock_sb_client)
        mock_sb_client.__exit__ = MagicMock(return_value=False)

        # First blob client succeeds; second raises
        good_blob = MagicMock()
        bad_blob = MagicMock()
        bad_blob.upload_blob.side_effect = RuntimeError("quota exceeded")

        call_count = {"n": 0}

        def blob_client_factory(container, blob):
            call_count["n"] += 1
            return good_blob if call_count["n"] == 1 else bad_blob

        mock_bsc_instance = MagicMock()
        mock_bsc_instance.get_blob_client.side_effect = blob_client_factory

        timer = MagicMock()
        timer.past_due = False

        with (
            patch.object(fa, "ServiceBusClient", return_value=mock_sb_client),
            patch.object(fa, "BlobServiceClient", return_value=mock_bsc_instance),
            patch.object(fa, "ManagedIdentityCredential"),
            patch.object(fa, "ClientAssertionCredential"),
        ):
            fa.service_bus_poller(timer)

        mock_receiver.complete_message.assert_called_once_with(msg_ok)
        mock_receiver.abandon_message.assert_called_once_with(msg_fail)
