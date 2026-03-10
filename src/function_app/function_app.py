"""
Azure Function App: Cross-Tenant Service Bus Subscriber

A timer-triggered function that polls a Service Bus topic subscription in a
remote Entra tenant (Tenant B) and persists each message payload as a JSON
blob in Azure Blob Storage in the local tenant (Tenant A).

Authentication overview
────────────────────────
Cross-tenant Service Bus access uses an explicit token-exchange chain so that
the correct Tenant B token is presented to Service Bus — avoiding the
``InvalidIssuer`` error produced by the legacy
``managedidentityasfederatedidentity`` runtime credential:

  UAMI (Tenant A)
    │
    │  ManagedIdentityCredential(client_id=UAMI)
    │  .get_token("api://AzureADTokenExchange")
    │  → short-lived federated token (Tenant A IMDS)
    ▼
  ClientAssertionCredential(
      tenant_id=<Tenant B>,
      client_id=<App Registration in Tenant B>,
      func=get_assertion,           # returns the federated token above
  )
    │
    │  client_assertion → Tenant B token exchange
    ▼
  ServiceBusClient(fully_qualified_namespace=..., credential=...)
    │
    ▼
  Service Bus topic subscription (Tenant B)

Blob Storage in Tenant A is reached with a separate UAMI credential:

  ManagedIdentityCredential(client_id=UAMI)
    │
    ▼
  BlobServiceClient (Tenant A Storage Account)

Required application settings
──────────────────────────────
CROSS_TENANT_SERVICE_BUS_NAMESPACE
                                – FQDN of the Service Bus namespace in Tenant B,
                                  e.g. mybus.servicebus.windows.net
CROSS_TENANT_TENANT_ID          – Entra Tenant ID of Tenant B
CROSS_TENANT_APP_CLIENT_ID      – Client ID of the multitenant App Registration
                                  in Tenant B
CROSS_TENANT_TOPIC_NAME         – Service Bus topic name
CROSS_TENANT_SUBSCRIPTION_NAME  – Service Bus subscription name
USER_ASSIGNED_MI_CLIENT_ID      – Client ID of the UAMI in Tenant A
STORAGE_ACCOUNT_NAME            – Storage account name (Tenant A)
STORAGE_CONTAINER_NAME          – Blob container name for received messages
TIMER_SCHEDULE                  – (optional) NCRONTAB schedule;
                                  default "0 */1 * * * *"
SB_MAX_MESSAGE_COUNT            – (optional) max messages per poll; default 100
SB_MAX_WAIT_TIME_SECONDS        – (optional) max wait time per poll in seconds;
                                  default 5
"""

import json
import logging
import os
import uuid
from datetime import UTC, datetime

import azure.functions as func
from azure.identity import ClientAssertionCredential, ManagedIdentityCredential
from azure.servicebus import ServiceBusClient, ServiceBusReceivedMessage
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

def _build_service_bus_credential() -> ClientAssertionCredential:
    """
    Build a ``ClientAssertionCredential`` that performs the cross-tenant token
    exchange required to authenticate against Service Bus in Tenant B.

    Flow:
      1. ``ManagedIdentityCredential`` obtains a short-lived federated token
         with audience ``api://AzureADTokenExchange`` from Tenant A's IMDS.
      2. ``ClientAssertionCredential`` presents that token as a client
         assertion to Tenant B's token endpoint, receiving a Tenant B token
         scoped to Service Bus.
    """
    tenant_id = _require_env("CROSS_TENANT_TENANT_ID")
    client_id = _require_env("CROSS_TENANT_APP_CLIENT_ID")
    uami_client_id = _require_env("USER_ASSIGNED_MI_CLIENT_ID")

    uami_credential = ManagedIdentityCredential(client_id=uami_client_id)

    def get_assertion() -> str:
        try:
            return uami_credential.get_token("api://AzureADTokenExchange").token
        except Exception as exc:
            raise RuntimeError(
                "Failed to obtain federated assertion token from IMDS for "
                "cross-tenant Service Bus authentication. Verify that the UAMI "
                f"'{uami_client_id}' is correctly assigned and IMDS is reachable."
            ) from exc

    return ClientAssertionCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        func=get_assertion,
    )


def _build_storage_credential() -> ManagedIdentityCredential:
    """
    Build a ``ManagedIdentityCredential`` scoped to the UAMI in Tenant A for
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
    message: ServiceBusReceivedMessage,
) -> str:
    """
    Persist a single Service Bus message payload as a JSON blob.

    Blob naming: ``<YYYY>/<MM>/<DD>/<message-id>.json``

    Returns the blob name that was written.
    """
    message_id = message.message_id or str(uuid.uuid4())
    date_prefix = datetime.now(UTC).strftime("%Y/%m/%d")
    blob_name = f"{date_prefix}/{message_id}.json"

    # ``message.body`` may be raw bytes or an iterable of bytes chunks.
    body = message.body
    try:
        payload_bytes: bytes = body if isinstance(body, bytes) else b"".join(body)
    except TypeError as exc:
        raise TypeError(
            f"Unexpected Service Bus message body format: {type(body).__name__}. "
            "Expected bytes or an iterable of bytes."
        ) from exc
    try:
        body_text = payload_bytes.decode("utf-8")
    except UnicodeDecodeError:
        body_text = payload_bytes.hex()

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

_TIMER_SCHEDULE = _opt_env("TIMER_SCHEDULE", "0 */1 * * * *")


@app.timer_trigger(
    schedule=_TIMER_SCHEDULE,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=False,
)
def service_bus_subscriber(timer: func.TimerRequest) -> None:
    """
    Timer-triggered function that polls a cross-tenant Service Bus topic
    subscription and writes each message to Azure Blob Storage.

    Uses ``ClientAssertionCredential`` for cross-tenant Service Bus access and
    ``ManagedIdentityCredential`` for same-tenant Blob Storage access.
    """
    if timer.past_due:
        logging.warning("Timer is past due; processing may have been delayed.")

    # ── Required configuration ────────────────────────────────────────────────
    sb_namespace = _require_env("CROSS_TENANT_SERVICE_BUS_NAMESPACE")
    topic_name = _require_env("CROSS_TENANT_TOPIC_NAME")
    subscription_name = _require_env("CROSS_TENANT_SUBSCRIPTION_NAME")
    storage_account_name = _require_env("STORAGE_ACCOUNT_NAME")
    container_name = _require_env("STORAGE_CONTAINER_NAME")

    # ── Optional configuration ────────────────────────────────────────────────
    max_message_count = int(_opt_env("SB_MAX_MESSAGE_COUNT", "100"))
    max_wait_time = float(_opt_env("SB_MAX_WAIT_TIME_SECONDS", "5"))

    # ── Credentials ───────────────────────────────────────────────────────────
    sb_credential = _build_service_bus_credential()
    storage_credential = _build_storage_credential()

    storage_url = f"https://{storage_account_name}.blob.core.windows.net"
    blob_service_client = BlobServiceClient(
        account_url=storage_url, credential=storage_credential
    )

    # ── Poll and process messages ─────────────────────────────────────────────
    processed = 0
    failed = 0

    with ServiceBusClient(
        fully_qualified_namespace=sb_namespace, credential=sb_credential
    ) as sb_client:
        with sb_client.get_subscription_receiver(
            topic_name=topic_name, subscription_name=subscription_name
        ) as receiver:
            messages = receiver.receive_messages(
                max_message_count=max_message_count,
                max_wait_time=max_wait_time,
            )
            for message in messages:
                try:
                    blob_name = _write_message_to_blob(
                        blob_service_client, container_name, message
                    )
                    receiver.complete_message(message)
                    logging.info(
                        "Message %s written to blob '%s'.",
                        message.message_id,
                        blob_name,
                    )
                    processed += 1
                except Exception:  # noqa: BLE001
                    logging.exception(
                        "Failed to process message %s; abandoning.",
                        message.message_id,
                    )
                    receiver.abandon_message(message)
                    failed += 1

    logging.info(
        "Poll complete: %d processed, %d failed/abandoned.", processed, failed
    )
