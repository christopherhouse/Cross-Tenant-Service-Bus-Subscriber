"""
Azure Function App: Cross-Tenant Service Bus Subscriber

This function runs on a timer and pulls messages from a Service Bus topic
subscription that lives in a SEPARATE Entra (Azure AD) tenant.

Cross-tenant authentication flow
─────────────────────────────────
1. A User Assigned Managed Identity (UAMI) is attached to this Function App
   in *Tenant A* (the hosting tenant).
2. In *Tenant B* (the Service Bus tenant) an App Registration exists that has
   a Federated Credential configured to trust the UAMI from Tenant A.
3. At runtime this function:
   a. Obtains a short-lived token from the UAMI scoped to
      "api://AzureADTokenExchange".
   b. Presents that token as a client_assertion to Tenant B via
      ClientAssertionCredential.
   c. Uses the resulting Tenant-B token to connect to the Service Bus.
4. Received message payloads are written as individual blobs to Azure Blob
   Storage in *Tenant A* using the same UAMI (same-tenant, no federation
   required – standard RBAC).

Required application settings
──────────────────────────────
CROSS_TENANT_SERVICE_BUS_NAMESPACE  – FQDN, e.g. mybus.servicebus.windows.net
CROSS_TENANT_TOPIC_NAME             – Service Bus topic name
CROSS_TENANT_SUBSCRIPTION_NAME      – Service Bus subscription name
CROSS_TENANT_TENANT_ID              – Entra tenant ID of Tenant B
CROSS_TENANT_APP_CLIENT_ID          – Client ID of the App Registration in Tenant B
USER_ASSIGNED_MI_CLIENT_ID          – Client ID of the UAMI in Tenant A
STORAGE_ACCOUNT_NAME                – Storage account name (Tenant A)
STORAGE_CONTAINER_NAME              – Blob container name for received messages
TIMER_SCHEDULE                      – NCRONTAB expression (default: every 60 s)
MAX_MESSAGE_BATCH_SIZE              – Max messages per timer invocation (default: 10)
"""

import json
import logging
import os
import uuid
from datetime import UTC, datetime

import azure.functions as func
from azure.identity import ClientAssertionCredential, ManagedIdentityCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.storage.blob import BlobServiceClient

# ──────────────────────────────────────────────────────────────────────────────
# Configuration helpers
# ──────────────────────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    """Return the value of an environment variable or raise if missing."""
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set."
        )
    return value


def _opt_env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# ──────────────────────────────────────────────────────────────────────────────
# Credential factories
# ──────────────────────────────────────────────────────────────────────────────

def _build_cross_tenant_credential() -> ClientAssertionCredential:
    """
    Build a ClientAssertionCredential that authenticates to Tenant B by
    exchanging a token obtained from the UAMI in Tenant A.
    """
    uami_client_id = _require_env("USER_ASSIGNED_MI_CLIENT_ID")
    cross_tenant_id = _require_env("CROSS_TENANT_TENANT_ID")
    cross_tenant_app_client_id = _require_env("CROSS_TENANT_APP_CLIENT_ID")

    # UAMI credential – used only to mint the assertion token
    uami_credential = ManagedIdentityCredential(client_id=uami_client_id)

    def _get_assertion() -> str:
        """
        Obtain a federated token from the UAMI to be used as a
        client_assertion when authenticating to Tenant B.
        """
        token = uami_credential.get_token("api://AzureADTokenExchange")
        return token.token

    return ClientAssertionCredential(
        tenant_id=cross_tenant_id,
        client_id=cross_tenant_app_client_id,
        func=_get_assertion,
    )


def _build_storage_credential() -> ManagedIdentityCredential:
    """
    Build a ManagedIdentityCredential scoped to the UAMI in Tenant A for
    accessing the Storage Account in the same tenant.
    """
    uami_client_id = _require_env("USER_ASSIGNED_MI_CLIENT_ID")
    return ManagedIdentityCredential(client_id=uami_client_id)


# ──────────────────────────────────────────────────────────────────────────────
# Message processing
# ──────────────────────────────────────────────────────────────────────────────

def _write_message_to_blob(
    blob_service_client: BlobServiceClient,
    container_name: str,
    message: ServiceBusMessage,
) -> str:
    """
    Persist a single Service Bus message payload as a blob.

    Blob naming: <ISO-date>/<message-id>.json
    Returns the blob name that was written.
    """
    message_id = message.message_id or str(uuid.uuid4())
    date_prefix = datetime.now(UTC).strftime("%Y/%m/%d")
    blob_name = f"{date_prefix}/{message_id}.json"

    # Build a structured envelope so consumers know the origin and metadata
    payload_bytes = message.body
    if isinstance(payload_bytes, (bytes, bytearray)):
        try:
            body_text = payload_bytes.decode("utf-8")
        except UnicodeDecodeError:
            body_text = payload_bytes.hex()
    else:
        # Generator or other iterable – materialise it
        body_text = b"".join(payload_bytes).decode("utf-8")

    envelope = {
        "messageId": message_id,
        "enqueuedAt": (
            message.enqueued_time_utc.isoformat()
            if message.enqueued_time_utc
            else None
        ),
        "receivedAt": datetime.now(UTC).isoformat(),
        "contentType": message.content_type,
        "subject": message.subject,
        "correlationId": message.correlation_id,
        "applicationProperties": dict(message.application_properties or {}),
        "body": body_text,
    }

    blob_client = blob_service_client.get_blob_client(
        container=container_name, blob=blob_name
    )
    blob_client.upload_blob(
        json.dumps(envelope, default=str).encode("utf-8"),
        overwrite=True,
    )
    return blob_name


# ──────────────────────────────────────────────────────────────────────────────
# Azure Function definition (Python v2 programming model)
# ──────────────────────────────────────────────────────────────────────────────

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

_TIMER_SCHEDULE = _opt_env("TIMER_SCHEDULE", "0 */1 * * * *")  # every minute


@app.timer_trigger(schedule=_TIMER_SCHEDULE, arg_name="timer", run_on_startup=False)
def service_bus_poller(timer: func.TimerRequest) -> None:
    """
    Timer-triggered function that polls a cross-tenant Service Bus topic
    subscription and forwards messages to Azure Blob Storage.
    """
    if timer.past_due:
        logging.warning("Timer is running late; processing will continue.")

    # ── Config ────────────────────────────────────────────────────────────────
    sb_namespace = _require_env("CROSS_TENANT_SERVICE_BUS_NAMESPACE")
    topic_name = _require_env("CROSS_TENANT_TOPIC_NAME")
    subscription_name = _require_env("CROSS_TENANT_SUBSCRIPTION_NAME")
    storage_account_name = _require_env("STORAGE_ACCOUNT_NAME")
    container_name = _require_env("STORAGE_CONTAINER_NAME")
    max_batch = int(_opt_env("MAX_MESSAGE_BATCH_SIZE", "10"))

    storage_url = f"https://{storage_account_name}.blob.core.windows.net"

    # ── Credentials ───────────────────────────────────────────────────────────
    cross_tenant_credential = _build_cross_tenant_credential()
    storage_credential = _build_storage_credential()

    # ── Clients ───────────────────────────────────────────────────────────────
    blob_service_client = BlobServiceClient(
        account_url=storage_url, credential=storage_credential
    )

    received_count = 0
    error_count = 0

    with ServiceBusClient(
        fully_qualified_namespace=sb_namespace,
        credential=cross_tenant_credential,
    ) as sb_client:
        with sb_client.get_subscription_receiver(
            topic_name=topic_name,
            subscription_name=subscription_name,
            max_wait_time=5,
        ) as receiver:
            messages = receiver.receive_messages(
                max_message_count=max_batch, max_wait_time=5
            )

            for msg in messages:
                try:
                    blob_name = _write_message_to_blob(
                        blob_service_client, container_name, msg
                    )
                    receiver.complete_message(msg)
                    received_count += 1
                    logging.info(
                        "Message %s written to blob '%s'.",
                        msg.message_id,
                        blob_name,
                    )
                except Exception:  # noqa: BLE001
                    logging.exception(
                        "Failed to process message %s; abandoning.",
                        msg.message_id,
                    )
                    receiver.abandon_message(msg)
                    error_count += 1

    logging.info(
        "Polling complete. received=%d errors=%d", received_count, error_count
    )
