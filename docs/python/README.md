# Cross-Tenant Service Bus Subscriber — Python (Legacy)

> **⚠️ Legacy implementation**
>
> The primary implementation of this project is now **C# .NET 10**.
> This document covers the original Python implementation, which is preserved
> for reference only. New development and deployments should use the C# .NET 10
> implementation described in the [root README](../../README.md).
>
> [![.NET 10](https://img.shields.io/badge/.NET-10-512BD4.svg)](https://dotnet.microsoft.com/download/dotnet/10.0)
> [![View primary README](https://img.shields.io/badge/Primary%20README-.NET%2010-blue)](../../README.md)

---

[![Deploy Function](https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/actions/workflows/deploy-function.yml/badge.svg)](https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/actions/workflows/deploy-function.yml)
[![Deploy Infrastructure](https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/actions/workflows/deploy-infra.yml/badge.svg)](https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/actions/workflows/deploy-infra.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../../LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Azure Functions v4](https://img.shields.io/badge/Azure%20Functions-v4-blue)](https://learn.microsoft.com/azure/azure-functions/)

An **Azure Function (Python)** that runs on a timer, polls a Service Bus
topic subscription hosted in a **separate Entra (Azure AD) tenant**, and
writes each received message payload as a JSON blob to Azure Blob Storage.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Tenant A  (Function hosting tenant)                           │
│                                                               │
│  ┌────────────────────────┐    ┌──────────────────────────┐  │
│  │  Azure Container       │    │  Storage Account         │  │
│  │  Registry (ACR)        │    │  /sb-messages/<date>/    │  │
│  └────────────┬───────────┘    └──────────────────────────┘  │
│    pull image │ (UAMI / AcrPull)              ▲              │
│               ▼                               │ write blobs  │
│  ┌────────────────────────────────────────────┴───────────┐  │
│  │  Azure Function  (timer, every 1 min)                  │  │
│  └─────────────────────────┬──────────────────────────────┘  │
│                             │ User Assigned MI (UAMI)         │
└─────────────────────────────┼────────────────────────────────┘
                              │
                              │  ClientAssertionCredential
                              │  UAMI token (api://AzureADTokenExchange)
                              │  → Tenant B App Registration (federated credential)
                              │  → Tenant B token → Service Bus Data Receiver
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ Tenant B  (Service Bus tenant)                                │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Service Bus Namespace                                 │    │
│  │  └─ Topic ─▶ Subscription                            │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### Authentication model

Cross-tenant Service Bus access uses an explicit token-exchange chain
implemented in the Python function code:

1. `ManagedIdentityCredential` obtains a short-lived federated token from the
   UAMI in Tenant A with audience `api://AzureADTokenExchange`.
2. `ClientAssertionCredential` presents that federated token as a client
   assertion to Tenant B's token endpoint, receiving a Tenant B access token
   scoped to Service Bus.
3. `ServiceBusClient` uses the Tenant B token to connect and receive messages.

Same-tenant Blob Storage access uses `ManagedIdentityCredential` directly
(no federation needed).

A **Tenant B administrator** must:
- Create an App Registration in Tenant B.
- Add a **Federated Credential** on that App Registration:
  - Issuer: `https://login.microsoftonline.com/<TENANT_A_ID>/v2.0`
  - Subject: the **Object (Principal) ID** of the UAMI (Bicep output: `uamiPrincipalId`)
  - Audience: `api://AzureADTokenExchange`
- Assign the App Registration's service principal the **Azure Service Bus Data
  Receiver** role on the Tenant B Service Bus namespace.

---

## Table of contents

- [Architecture](#architecture)
- [Repository structure](#repository-structure)
- [Prerequisites](#prerequisites)
- [One-time setup](#one-time-setup)
- [Deployment](#deployment)
- [Local development](#local-development)
- [Running tests](#running-tests)
- [Application settings reference](#application-settings-reference)
- [GitHub Copilot Coding Agent](#github-copilot-coding-agent)
- [Security notes](#security-notes)
- [Contributing](#contributing)
- [License](#license)

---

## Repository structure

```
.
├── src/
│   └── function_app/
│       ├── Dockerfile                      # Container image (mcr.microsoft.com/azure-functions/python:4-python3.13)
│       ├── .dockerignore                   # Docker build context exclusions
│       ├── function_app.py                 # Timer trigger, cross-tenant Service Bus poll, blob write
│       ├── host.json                       # Azure Functions host config
│       ├── requirements.txt                # Python dependencies
│       └── local.settings.json.template    # Local dev config template
├── infra/
│   ├── main.bicep                          # Root Bicep template
│   ├── main.bicepparam                     # Parameter values
│   └── modules/
│       ├── user-assigned-identity.bicep
│       ├── storage-account.bicep
│       ├── app-service-plan.bicep
│       ├── function-app.bicep
│       ├── container-registry.bicep        # Azure Container Registry (Basic SKU) + AcrPull role
│       ├── log-analytics-workspace.bicep
│       └── app-insights.bicep
├── .github/
│   ├── copilot-instructions.md             # Copilot Coding Agent repo context
│   ├── agents/
│   │   ├── bicep-infrastructure.md         # Bicep specialist agent
│   │   ├── python-function.md              # Python function specialist agent
│   │   ├── cicd-workflow.md                # CI/CD specialist agent
│   │   └── documentation.md               # Documentation specialist agent
│   └── workflows/
│       ├── deploy-infra.yml                # Bicep deployment workflow
│       └── deploy-function.yml             # Container build and deployment workflow
└── tests/
    └── test_function_app.py                # pytest unit tests
```

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.13+ | Required for running tests locally |
| Azure CLI | latest | Required for all deployments |
| Bicep CLI | latest (`az bicep install`) | Required for infrastructure deployments |
| Azure Functions Core Tools | v4 | Optional — for `func start` local development only |
| Docker | latest | Optional — for building and running the container locally; CI/CD uses `az acr build` (no local Docker daemon required) |

---

## One-time setup

### 1 – Provision a service principal for GitHub Actions (Tenant A)

This service principal is used **only by the CI/CD workflows** to deploy
infrastructure and the function code.

```bash
# Create the service principal
az ad sp create-for-rbac --name "sp-sbsub-github-actions" --skip-assignment

# Assign roles on the resource group (create the RG first if needed)
az role assignment create \
  --assignee <sp-client-id> \
  --role "Contributor" \
  --scope /subscriptions/<subscription-id>/resourceGroups/<rg-name>

az role assignment create \
  --assignee <sp-client-id> \
  --role "User Access Administrator" \
  --scope /subscriptions/<subscription-id>/resourceGroups/<rg-name>
```

Add a **Federated Credential** on the App Registration for GitHub OIDC:
- Issuer: `https://token.actions.githubusercontent.com`
- Subject: `repo:<org>/<repo>:environment:<env-name>`
- Audience: `api://AzureADTokenExchange`

### 2 – Configure GitHub Actions Secrets and Variables

**Secrets** (repository or environment level):

| Secret | Value |
|---|---|
| `AZURE_CLIENT_ID` | Deployment SP client ID |
| `AZURE_TENANT_ID` | Tenant A ID |
| `AZURE_SUBSCRIPTION_ID` | Subscription ID |

**Variables**:

| Variable | Example | Notes |
|---|---|---|
| `AZURE_RG_NAME` | `rg-sbsub-dev` | |
| `AZURE_LOCATION` | `eastus` | Used by `deploy-infra.yml` |
| `ENVIRONMENT_NAME` | `dev` | |
| `WORKLOAD_NAME` | `sbsub` | Used to derive the image name (`func-<workload>-<env>`) |
| `ACR_NAME` | `crsbsubdev` | Name of the Azure Container Registry (output by infra deployment); used by `deploy-function.yml` |
| `CROSS_TENANT_SB_NAMESPACE` | `mybus.servicebus.windows.net` | Fully-qualified Service Bus namespace hostname; used by `deploy-infra.yml` |
| `CROSS_TENANT_TENANT_ID` | Entra Tenant ID of Tenant B | |
| `CROSS_TENANT_APP_CLIENT_ID` | Client ID of the App Registration in Tenant B | |
| `CROSS_TENANT_TOPIC_NAME` | `orders` | |
| `CROSS_TENANT_SUBSCRIPTION_NAME` | `fn-subscriber` | |
| `AZURE_FUNCTION_APP_NAME` | `func-sbsub-dev` | |

### 3 – Set up cross-tenant access in Tenant B

A **Tenant B administrator** must complete the following steps so the function
can authenticate to Tenant B's Service Bus.

**3a – Create an App Registration in Tenant B.**

In the Azure portal for Tenant B, create a new App Registration (the name is
arbitrary, e.g. `app-sbsub-cross-tenant`).

**3b – Add a Federated Credential on the App Registration.**

Navigate to the App Registration → **Certificates & secrets** →
**Federated credentials** → **Add credential**.

| Field | Value |
|---|---|
| Scenario | Other issuer |
| Issuer | `https://login.microsoftonline.com/<TENANT_A_ID>/v2.0` |
| Subject identifier | Object (Principal) ID of the UAMI (Bicep output: `uamiPrincipalId`) |
| Audience | `api://AzureADTokenExchange` |

**3c – Assign the Service Bus Data Receiver role.**

Assign the App Registration's **service principal** (Enterprise Application)
the **Azure Service Bus Data Receiver** RBAC role on the Tenant B namespace:

```bash
az role assignment create \
  --assignee <app-registration-service-principal-object-id> \
  --role "Azure Service Bus Data Receiver" \
  --scope /subscriptions/<tenant-b-subscription-id>/resourceGroups/<rg>/providers/Microsoft.ServiceBus/namespaces/<namespace>
```

---

## Deployment

### Deploy infrastructure

```bash
# Manually via Azure CLI
az deployment group create \
  --resource-group rg-sbsub-dev \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam
```

Or push a change to `infra/**` on `main` to trigger the
`.github/workflows/deploy-infra.yml` workflow automatically.

After the first deployment, note the `uamiPrincipalId` output and use it when
granting the UAMI access to the Service Bus namespace in Tenant B (step 3 above).

### Deploy function code

The function runs as a Docker container pulled from Azure Container Registry.
The CI/CD workflow uses **ACR Tasks** (`az acr build`) so no local Docker
daemon is required on the runner.

```bash
# Set your values
ACR_NAME="<acr-name>"          # from the ACR_NAME GitHub Variable / infra output
IMAGE_NAME="func-<workload-name>-<environment-name>"  # e.g. func-sbsub-dev
RG_NAME="<resource-group-name>"
FUNC_APP_NAME="<function-app-name>"

# 1. Build the container image inside ACR Tasks and push it
az acr build \
  --registry "$ACR_NAME" \
  --image "$IMAGE_NAME:latest" \
  src/function_app

# 2. Update the Function App to pull the new image
az functionapp config container set \
  --resource-group "$RG_NAME" \
  --name "$FUNC_APP_NAME" \
  --image "$ACR_NAME.azurecr.io/$IMAGE_NAME:latest"
```

Or push a change to `src/function_app/**` on `main` to trigger the
`.github/workflows/deploy-function.yml` workflow automatically.  The workflow
tags images with the commit SHA for full traceability.

---

## Local development

### Option A — Azure Functions Core Tools (`func start`)

```bash
# 1. Install dependencies
cd src/function_app
pip install -r requirements.txt

# 2. Copy and fill in settings
cp local.settings.json.template local.settings.json
# Edit local.settings.json with real values

# 3. Start the function locally
func start
```

### Option B — Docker

`local.settings.json` is a JSON file, so you must first extract the `Values`
block into a `.env` file (KEY=VALUE, one per line):

```bash
# Requires jq (https://jqlang.github.io/jq/)
jq -r '.Values | to_entries[] | "\(.key)=\(.value)"' \
  src/function_app/local.settings.json > src/function_app/.env
```

Then build and run the container:

```bash
# 1. Build the container image locally
docker build -t func-sbsub-local src/function_app/

# 2. Run the container with the extracted settings
docker run -p 7071:80 \
  --env-file src/function_app/.env \
  func-sbsub-local
```

> **Note**: Add `src/function_app/.env` to `.gitignore` — it contains real
> credentials and must never be committed.

> **Note**: The UAMI is only available when running inside Azure. For local
> testing, populate `local.settings.json` with all `CROSS_TENANT_*` and
> `USER_ASSIGNED_MI_CLIENT_ID` values. The `ClientAssertionCredential` token
> exchange requires a valid UAMI, so cross-tenant federation must be configured
> even for local runs. If your developer account has direct **Azure Service Bus
> Data Receiver** access in both tenants you can substitute `AzureCliCredential`
> in the code temporarily, but this is not the production path.

---

## Running tests

```bash
pip install pytest pytest-mock
python -m pytest tests/ -v
```

---

## Application settings reference

| Setting | Description |
|---|---|
| `CROSS_TENANT_SERVICE_BUS_NAMESPACE` | FQDN of the Service Bus namespace, e.g. `mybus.servicebus.windows.net` |
| `CROSS_TENANT_TENANT_ID` | Entra Tenant ID of Tenant B |
| `CROSS_TENANT_APP_CLIENT_ID` | Client ID of the App Registration in Tenant B |
| `CROSS_TENANT_TOPIC_NAME` | Topic name |
| `CROSS_TENANT_SUBSCRIPTION_NAME` | Subscription name |
| `USER_ASSIGNED_MI_CLIENT_ID` | Client ID of the UAMI in Tenant A |
| `STORAGE_ACCOUNT_NAME` | Storage account name (Tenant A) |
| `STORAGE_CONTAINER_NAME` | Blob container for received messages |
| `TIMER_SCHEDULE` | (optional) NCRONTAB schedule, default `0 */1 * * * *` |
| `SB_MAX_MESSAGE_COUNT` | (optional) max messages per poll, default `100` |
| `SB_MAX_WAIT_TIME_SECONDS` | (optional) max wait time per poll in seconds, default `5` |

---

## GitHub Copilot Coding Agent

This repository ships four specialist Copilot Coding Agents in `.github/agents/`
to facilitate "vibe coding":

| Agent | File | Purpose |
|---|---|---|
| Bicep Infrastructure | `bicep-infrastructure.md` | Author/review Bicep templates |
| Python Function | `python-function.md` | Author/review function code |
| CI/CD Workflow | `cicd-workflow.md` | Author/review GitHub Actions workflows |
| Documentation | `documentation.md` | Maintain README and open-source docs |

Global repository context and conventions are defined in
`.github/copilot-instructions.md`.

---

## Security notes

- **No secrets in code or Bicep**: all credentials flow through managed identities
  and OIDC.
- Storage access uses identity-based `AzureWebJobsStorage__accountName` (no
  connection string).
- ACR pull uses UAMI-based managed identity (`acrUseManagedIdentityCreds: true`);
  no registry credentials are stored in app settings or source code.
- FTPS is disabled; minimum TLS 1.2 enforced on the Function App.
- Blob container public access is disabled.

See [SECURITY.md](SECURITY.md) for the full security policy and vulnerability
reporting process.

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for
coding conventions, branch naming, commit message format, and the pull request
process.

---

## License

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
