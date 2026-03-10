"""
Azure Function App: Cross-Tenant Service Bus Subscriber

This function is triggered directly by new messages arriving on a Service Bus
topic subscription. The Azure Functions runtime manages the Service Bus
connection and message receipt using identity-based authentication; there is
no polling loop in this code.

Received message payloads are written as individual blobs to Azure Blob
Storage in Tenant A using the same User Assigned Managed Identity (UAMI).

Authentication overview
────────────────────────
Both the Service Bus trigger and the Storage Account use the UAMI:

  UAMI (Tenant A)
    │
    ├─ Service Bus trigger (cross-tenant federated identity via Functions runtime)
    │    SERVICE_BUS_CONNECTION__fullyQualifiedNamespace
    │    SERVICE_BUS_CONNECTION__credential          = "managedidentityasfederatedidentity"
    │    SERVICE_BUS_CONNECTION__azureCloud          = "public"
    │    SERVICE_BUS_CONNECTION__clientId            = <App Registration client ID in Tenant B>
    │    SERVICE_BUS_CONNECTION__tenantId            = <Tenant B ID>
    │    SERVICE_BUS_CONNECTION__managedIdentityClientId = <UAMI client ID>
    │
    │    Token-exchange flow:
    │      UAMI token (Tenant A) → federated credential on App Registration (Tenant B)
    │      → Tenant B token → Service Bus Data Receiver access on Tenant B namespace
    │
    └─ ManagedIdentityCredential(client_id=UAMI)
         │
         ▼
       BlobServiceClient (Tenant A Storage Account)

Important: On Consumption and Flex Consumption plans, configuring a trigger
with a cross-tenant connection disables platform-based auto-scaling for that
trigger (see https://aka.ms/functions-cross-tenant-connections).  The function
still fires; manual or metric-based scaling rules can compensate if needed.

Required application settings
──────────────────────────────
SERVICE_BUS_CONNECTION__fullyQualifiedNamespace
                                – FQDN of the Service Bus namespace in Tenant B,
                                  e.g. mybus.servicebus.windows.net
SERVICE_BUS_CONNECTION__credential
                                – Must be "managedidentityasfederatedidentity"
                                  for cross-tenant access
SERVICE_BUS_CONNECTION__azureCloud
                                – Cloud environment; use "public" for Azure
                                  Public Cloud
SERVICE_BUS_CONNECTION__clientId
                                – Client ID of the multitenant App Registration
                                  in Tenant B (crossTenantAppClientId)
SERVICE_BUS_CONNECTION__tenantId
                                – Entra Tenant ID of Tenant B
SERVICE_BUS_CONNECTION__managedIdentityClientId
                                – Client ID of the UAMI in Tenant A (same
                                  value as USER_ASSIGNED_MI_CLIENT_ID)
CROSS_TENANT_TOPIC_NAME         – Service Bus topic name
CROSS_TENANT_SUBSCRIPTION_NAME  – Service Bus subscription name
USER_ASSIGNED_MI_CLIENT_ID      – Client ID of the UAMI in Tenant A
STORAGE_ACCOUNT_NAME            – Storage account name (Tenant A)
STORAGE_CONTAINER_NAME          – Blob container name for received messages
"""

import json
import logging
import os
import uuid
from datetime import UTC, datetime

import azure.functions as func
from azure.identity import ManagedIdentityCredential
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
    message: func.ServiceBusMessage,
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
    payload_bytes = message.get_body()
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

_SB_TOPIC = _opt_env("CROSS_TENANT_TOPIC_NAME", "")
_SB_SUBSCRIPTION = _opt_env("CROSS_TENANT_SUBSCRIPTION_NAME", "")


@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name=_SB_TOPIC,
    subscription_name=_SB_SUBSCRIPTION,
    connection="SERVICE_BUS_CONNECTION",
)
def service_bus_subscriber(message: func.ServiceBusMessage) -> None:
    """
    Service Bus–triggered function that processes messages from a cross-tenant
    Service Bus topic subscription and forwards them to Azure Blob Storage.
    """
    storage_account_name = _require_env("STORAGE_ACCOUNT_NAME")
    container_name = _require_env("STORAGE_CONTAINER_NAME")

    storage_url = f"https://{storage_account_name}.blob.core.windows.net"
    storage_credential = _build_storage_credential()

    blob_service_client = BlobServiceClient(
        account_url=storage_url, credential=storage_credential
    )

    try:
        blob_name = _write_message_to_blob(
            blob_service_client, container_name, message
        )
        logging.info(
            "Message %s written to blob '%s'.",
            message.message_id,
            blob_name,
        )
    except Exception:  # noqa: BLE001 – catch-all so any failure abandons the message
        logging.exception(
            "Failed to process message %s; re-raising so the runtime abandons it.",
            message.message_id,
        )
        raise
