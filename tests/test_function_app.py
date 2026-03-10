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
    """Create a mock ServiceBusReceivedMessage."""
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
        "CROSS_TENANT_TENANT_ID": "tenant-b-id",
        "CROSS_TENANT_APP_CLIENT_ID": "app-reg-client-id-in-tenant-b",
        "CROSS_TENANT_TOPIC_NAME": "test-topic",
        "CROSS_TENANT_SUBSCRIPTION_NAME": "test-sub",
        "USER_ASSIGNED_MI_CLIENT_ID": "uami-client-id",
        "STORAGE_ACCOUNT_NAME": "teststorage",
        "STORAGE_CONTAINER_NAME": "sb-messages",
    }
    if extra:
        env.update(extra)
    return env


def _make_timer(past_due: bool = False):
    """Create a mock func.TimerRequest."""
    timer = MagicMock()
    timer.past_due = past_due
    return timer


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


# ── Tests: _build_service_bus_credential ─────────────────────────────────────

class TestBuildServiceBusCredential:
    def test_returns_client_assertion_credential(self, monkeypatch):
        """_build_service_bus_credential must return a ClientAssertionCredential."""
        import importlib
        import function_app as fa
        importlib.reload(fa)

        for k, v in _base_env().items():
            monkeypatch.setenv(k, v)

        mock_token = MagicMock()
        mock_token.token = "fake-federated-token"

        with (
            patch.object(fa, "ManagedIdentityCredential") as mock_mic,
            patch.object(fa, "ClientAssertionCredential") as mock_cac,
        ):
            mock_mic_instance = MagicMock()
            mock_mic_instance.get_token.return_value = mock_token
            mock_mic.return_value = mock_mic_instance

            fa._build_service_bus_credential()

            mock_cac.assert_called_once()
            _, kwargs = mock_cac.call_args
            assert kwargs["tenant_id"] == "tenant-b-id"
            assert kwargs["client_id"] == "app-reg-client-id-in-tenant-b"
            assert callable(kwargs["func"])

    def test_assertion_func_calls_uami_get_token(self, monkeypatch):
        """The inner get_assertion() must call get_token with the correct audience."""
        import importlib
        import function_app as fa
        importlib.reload(fa)

        for k, v in _base_env().items():
            monkeypatch.setenv(k, v)

        mock_token = MagicMock()
        mock_token.token = "fake-federated-token"

        captured_assertion_func = None

        def capture_cac(**kwargs):
            nonlocal captured_assertion_func
            captured_assertion_func = kwargs["func"]
            return MagicMock()

        with (
            patch.object(fa, "ManagedIdentityCredential") as mock_mic,
            patch.object(fa, "ClientAssertionCredential", side_effect=capture_cac),
        ):
            mock_mic_instance = MagicMock()
            mock_mic_instance.get_token.return_value = mock_token
            mock_mic.return_value = mock_mic_instance

            fa._build_service_bus_credential()

            assert captured_assertion_func is not None
            token_value = captured_assertion_func()
            mock_mic_instance.get_token.assert_called_with(
                "api://AzureADTokenExchange"
            )
            assert token_value == "fake-federated-token"

    def test_assertion_func_wraps_get_token_error(self, monkeypatch):
        """A get_token failure must be re-raised as RuntimeError with context."""
        import importlib
        import function_app as fa
        importlib.reload(fa)

        for k, v in _base_env().items():
            monkeypatch.setenv(k, v)

        captured_assertion_func = None

        def capture_cac(**kwargs):
            nonlocal captured_assertion_func
            captured_assertion_func = kwargs["func"]
            return MagicMock()

        with (
            patch.object(fa, "ManagedIdentityCredential") as mock_mic,
            patch.object(fa, "ClientAssertionCredential", side_effect=capture_cac),
        ):
            mock_mic_instance = MagicMock()
            mock_mic_instance.get_token.side_effect = Exception("IMDS unavailable")
            mock_mic.return_value = mock_mic_instance

            fa._build_service_bus_credential()

            assert captured_assertion_func is not None
            with pytest.raises(RuntimeError, match="cross-tenant Service Bus"):
                captured_assertion_func()


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

    def test_body_as_iterable_of_bytes(self):
        """Body supplied as an iterable of byte chunks must be joined correctly."""
        import function_app as fa

        mock_blob_client = MagicMock()
        mock_bsc = MagicMock()
        mock_bsc.get_blob_client.return_value = mock_blob_client

        msg = _make_sb_message()
        msg.body = iter([b'{"chunked":', b' "body"}'])

        fa._write_message_to_blob(mock_bsc, "container", msg)

        upload_args = mock_blob_client.upload_blob.call_args
        payload = json.loads(upload_args[0][0].decode("utf-8"))
        assert payload["body"] == '{"chunked": "body"}'

    def test_body_invalid_type_raises_type_error(self):
        """An iterable containing non-bytes elements must raise TypeError with context."""
        import function_app as fa

        mock_bsc = MagicMock()
        mock_bsc.get_blob_client.return_value = MagicMock()

        msg = _make_sb_message()
        msg.body = iter(["not bytes", "also not bytes"])  # strings, not bytes

        with pytest.raises(TypeError, match="Unexpected Service Bus message body format"):
            fa._write_message_to_blob(mock_bsc, "container", msg)


# ── Tests: service_bus_subscriber (timer trigger, fully mocked) ───────────────

class TestServiceBusSubscriber:
    """Tests for the timer-triggered function."""

    def _patch_env(self, monkeypatch, extra=None):
        env = _base_env(extra)
        for k, v in env.items():
            monkeypatch.setenv(k, v)

    def _make_receiver_context(self, messages):
        """Build a mock context manager that returns `messages` from receive_messages."""
        receiver = MagicMock()
        receiver.receive_messages.return_value = messages
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=receiver)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx, receiver

    def _make_sb_client_context(self, receiver_ctx):
        """Build a mock ServiceBusClient context manager."""
        sb_client = MagicMock()
        sb_client.get_subscription_receiver.return_value = receiver_ctx
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=sb_client)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx, sb_client

    def test_happy_path_writes_blob_and_completes_message(self, monkeypatch):
        """Each received message must be written to blob then completed."""
        import importlib
        import function_app as fa
        importlib.reload(fa)
        self._patch_env(monkeypatch)

        msg = _make_sb_message()
        receiver_ctx, receiver = self._make_receiver_context([msg])
        sb_client_ctx, sb_client = self._make_sb_client_context(receiver_ctx)

        mock_blob_client = MagicMock()
        mock_bsc_instance = MagicMock()
        mock_bsc_instance.get_blob_client.return_value = mock_blob_client

        with (
            patch.object(fa, "ServiceBusClient", return_value=sb_client_ctx),
            patch.object(fa, "BlobServiceClient", return_value=mock_bsc_instance),
            patch.object(fa, "_build_service_bus_credential"),
            patch.object(fa, "_build_storage_credential"),
        ):
            fa.service_bus_subscriber(_make_timer())

        mock_blob_client.upload_blob.assert_called_once()
        receiver.complete_message.assert_called_once_with(msg)
        receiver.abandon_message.assert_not_called()

    def test_blob_write_failure_abandons_message(self, monkeypatch):
        """When blob write fails the message must be abandoned (not re-raised)."""
        import importlib
        import function_app as fa
        importlib.reload(fa)
        self._patch_env(monkeypatch)

        msg = _make_sb_message()
        receiver_ctx, receiver = self._make_receiver_context([msg])
        sb_client_ctx, _ = self._make_sb_client_context(receiver_ctx)

        mock_blob_client = MagicMock()
        mock_blob_client.upload_blob.side_effect = RuntimeError("disk full")
        mock_bsc_instance = MagicMock()
        mock_bsc_instance.get_blob_client.return_value = mock_blob_client

        with (
            patch.object(fa, "ServiceBusClient", return_value=sb_client_ctx),
            patch.object(fa, "BlobServiceClient", return_value=mock_bsc_instance),
            patch.object(fa, "_build_service_bus_credential"),
            patch.object(fa, "_build_storage_credential"),
        ):
            # Must NOT raise — errors are caught per-message
            fa.service_bus_subscriber(_make_timer())

        receiver.complete_message.assert_not_called()
        receiver.abandon_message.assert_called_once_with(msg)

    def test_empty_batch_no_blob_writes(self, monkeypatch):
        """When there are no messages, no blobs should be written."""
        import importlib
        import function_app as fa
        importlib.reload(fa)
        self._patch_env(monkeypatch)

        receiver_ctx, receiver = self._make_receiver_context([])
        sb_client_ctx, _ = self._make_sb_client_context(receiver_ctx)

        mock_bsc_instance = MagicMock()

        with (
            patch.object(fa, "ServiceBusClient", return_value=sb_client_ctx),
            patch.object(fa, "BlobServiceClient", return_value=mock_bsc_instance),
            patch.object(fa, "_build_service_bus_credential"),
            patch.object(fa, "_build_storage_credential"),
        ):
            fa.service_bus_subscriber(_make_timer())

        mock_bsc_instance.get_blob_client.assert_not_called()

    def test_multiple_messages_processed_independently(self, monkeypatch):
        """A failure on one message must not stop processing of subsequent messages."""
        import importlib
        import function_app as fa
        importlib.reload(fa)
        self._patch_env(monkeypatch)

        msg_ok = _make_sb_message(message_id="ok-msg")
        msg_fail = _make_sb_message(message_id="fail-msg")
        receiver_ctx, receiver = self._make_receiver_context([msg_fail, msg_ok])
        sb_client_ctx, _ = self._make_sb_client_context(receiver_ctx)

        fail_blob_client = MagicMock()
        fail_blob_client.upload_blob.side_effect = RuntimeError("transient error")
        ok_blob_client = MagicMock()

        mock_bsc_instance = MagicMock()
        mock_bsc_instance.get_blob_client.side_effect = [
            fail_blob_client,
            ok_blob_client,
        ]

        with (
            patch.object(fa, "ServiceBusClient", return_value=sb_client_ctx),
            patch.object(fa, "BlobServiceClient", return_value=mock_bsc_instance),
            patch.object(fa, "_build_service_bus_credential"),
            patch.object(fa, "_build_storage_credential"),
        ):
            fa.service_bus_subscriber(_make_timer())

        receiver.abandon_message.assert_called_once_with(msg_fail)
        receiver.complete_message.assert_called_once_with(msg_ok)

    def test_past_due_timer_logs_warning(self, monkeypatch, caplog):
        """A past-due timer must emit a warning log."""
        import importlib
        import logging
        import function_app as fa
        importlib.reload(fa)
        self._patch_env(monkeypatch)

        receiver_ctx, _ = self._make_receiver_context([])
        sb_client_ctx, _ = self._make_sb_client_context(receiver_ctx)

        with (
            patch.object(fa, "ServiceBusClient", return_value=sb_client_ctx),
            patch.object(fa, "BlobServiceClient"),
            patch.object(fa, "_build_service_bus_credential"),
            patch.object(fa, "_build_storage_credential"),
            caplog.at_level(logging.WARNING),
        ):
            fa.service_bus_subscriber(_make_timer(past_due=True))

        assert any("past due" in r.message.lower() for r in caplog.records)

    def test_missing_required_env_var_raises(self, monkeypatch):
        """Missing STORAGE_ACCOUNT_NAME must raise EnvironmentError."""
        import importlib
        import function_app as fa
        importlib.reload(fa)

        env = _base_env()
        env.pop("STORAGE_ACCOUNT_NAME", None)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("STORAGE_ACCOUNT_NAME", raising=False)

        with (
            patch.object(fa, "ServiceBusClient"),
            patch.object(fa, "BlobServiceClient"),
            patch.object(fa, "_build_service_bus_credential"),
            patch.object(fa, "_build_storage_credential"),
        ):
            with pytest.raises(EnvironmentError, match="STORAGE_ACCOUNT_NAME"):
                fa.service_bus_subscriber(_make_timer())

    def test_receive_messages_uses_correct_params(self, monkeypatch):
        """receive_messages must be called with the configured count and wait time."""
        import importlib
        import function_app as fa
        importlib.reload(fa)
        self._patch_env(monkeypatch, extra={
            "SB_MAX_MESSAGE_COUNT": "42",
            "SB_MAX_WAIT_TIME_SECONDS": "3",
        })

        receiver_ctx, receiver = self._make_receiver_context([])
        sb_client_ctx, _ = self._make_sb_client_context(receiver_ctx)

        with (
            patch.object(fa, "ServiceBusClient", return_value=sb_client_ctx),
            patch.object(fa, "BlobServiceClient"),
            patch.object(fa, "_build_service_bus_credential"),
            patch.object(fa, "_build_storage_credential"),
        ):
            fa.service_bus_subscriber(_make_timer())

        receiver.receive_messages.assert_called_once_with(
            max_message_count=42, max_wait_time=3.0
        )
