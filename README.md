# Cross-Tenant Service Bus Subscriber

[![Deploy Function](https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/actions/workflows/deploy-function.yml/badge.svg)](https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/actions/workflows/deploy-function.yml)
[![Deploy Infrastructure](https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/actions/workflows/deploy-infra.yml/badge.svg)](https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/actions/workflows/deploy-infra.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Azure Functions v4](https://img.shields.io/badge/Azure%20Functions-v4-blue)](https://learn.microsoft.com/azure/azure-functions/)

An **Azure Function (Python)** that runs on a timer, polls a Service Bus
topic subscription hosted in a **separate Entra (Azure AD) tenant**, and
writes each received message payload as a JSON blob to Azure Blob Storage.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ Tenant A  (Function hosting tenant)                  │
│                                                      │
│  ┌──────────────────────┐    ┌───────────────────────┐  │
│  │  Azure Function      │    │  Storage Account      │  │
│  │  (timer, every 1 min)│───▶│  /sb-messages/<date>/ │  │
│  └──────────┬───────────┘    └───────────────────────┘  │
│             │ User Assigned MI (UAMI)                 │
└─────────────┼───────────────────────────────────────┘
              │
              │  ClientAssertionCredential
              │  UAMI token (api://AzureADTokenExchange)
              │  → Tenant B App Registration (federated credential)
              │  → Tenant B token → Service Bus Data Receiver
              ▼
┌─────────────────────────────────────────────────────┐
│ Tenant B  (Service Bus tenant)                       │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │ Service Bus Namespace                        │    │
│  │  └─ Topic ─▶ Subscription                   │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
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

## Repository structure

```
.
├── src/
│   └── function_app/
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
│       ├── log-analytics-workspace.bicep
│       └── app-insights.bicep
├── .github/
│   ├── copilot-instructions.md             # Copilot Coding Agent repo context
│   ├── agents/
│   │   ├── bicep-infrastructure.md         # Bicep specialist agent
│   │   ├── python-function.md              # Python function specialist agent
│   │   └── cicd-workflow.md                # CI/CD specialist agent
│   └── workflows/
│       ├── deploy-infra.yml                # Bicep deployment workflow
│       └── deploy-function.yml             # Function code deployment workflow
└── tests/
    └── test_function_app.py                # pytest unit tests
```

---

## Prerequisites

| Tool | Version |
|---|---|
| Python | 3.13+ |
| Azure Functions Core Tools | v4 |
| Azure CLI | latest |
| Bicep CLI | latest (`az bicep install`) |

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

| Variable | Example |
|---|---|
| `AZURE_RG_NAME` | `rg-sbsub-dev` |
| `AZURE_LOCATION` | `eastus` |
| `ENVIRONMENT_NAME` | `dev` |
| `WORKLOAD_NAME` | `sbsub` |
| `SERVICE_BUS_FQNS` | `mybus.servicebus.windows.net` |
| `CROSS_TENANT_TENANT_ID` | Entra Tenant ID of Tenant B |
| `CROSS_TENANT_APP_CLIENT_ID` | Client ID of the App Registration in Tenant B |
| `CROSS_TENANT_TOPIC_NAME` | `orders` |
| `CROSS_TENANT_SUBSCRIPTION_NAME` | `fn-subscriber` |
| `AZURE_FUNCTION_APP_NAME` | `func-sbsub-dev` |

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

```bash
# Manually via Azure Functions Core Tools
cd src/function_app
func azure functionapp publish func-sbsub-dev
```

Or push a change to `src/function_app/**` on `main` to trigger the
`.github/workflows/deploy-function.yml` workflow automatically.

---

## Local development

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
