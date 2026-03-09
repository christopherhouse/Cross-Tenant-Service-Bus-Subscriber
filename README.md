# Cross-Tenant Service Bus Subscriber

An **Azure Function (Python)** that polls a Service Bus topic subscription
hosted in a **separate Entra (Azure AD) tenant** and writes each received
message payload as a JSON blob to Azure Blob Storage.

Authentication to the remote Service Bus is handled with **zero secrets** using
a User Assigned Managed Identity (UAMI) in the hosting tenant combined with a
Federated Credential on an App Registration in the Service Bus tenant
(`ClientAssertionCredential`).

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ Tenant A  (Function hosting tenant)                  │
│                                                      │
│  ┌──────────────────┐    ┌───────────────────────┐  │
│  │  Azure Function  │    │  Storage Account      │  │
│  │  (timer, 1 min)  │───▶│  /sb-messages/<date>/ │  │
│  └──────┬───────────┘    └───────────────────────┘  │
│         │ User Assigned MI (id-sbsub-dev)             │
└─────────┼───────────────────────────────────────────┘
          │
          │  ClientAssertionCredential
          │  (UAMI token → federated exchange → Tenant B token)
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

### Cross-tenant authentication flow

1. The UAMI in Tenant A requests a token scoped to `api://AzureADTokenExchange`.
2. That token is used as a `client_assertion` with `ClientAssertionCredential`
   targeting Tenant B.
3. Tenant B's App Registration has a **Federated Credential** that trusts the
   UAMI's subject (its Object/Principal ID), so it exchanges the assertion for a
   Tenant B access token.
4. The Tenant B token is used to authenticate `ServiceBusClient`.

Same-tenant Blob Storage access uses `ManagedIdentityCredential` directly (no
federation needed).

---

## Repository structure

```
.
├── src/
│   └── function_app/
│       ├── function_app.py                 # Timer trigger, auth, blob write
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
| Python | 3.11+ |
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
| `CROSS_TENANT_SB_NAMESPACE` | `mybus.servicebus.windows.net` |
| `CROSS_TENANT_TOPIC_NAME` | `orders` |
| `CROSS_TENANT_SUBSCRIPTION_NAME` | `fn-subscriber` |
| `CROSS_TENANT_TENANT_ID` | `<tenant-b-id>` |
| `CROSS_TENANT_APP_CLIENT_ID` | `<app-reg-client-id-tenant-b>` |
| `AZURE_FUNCTION_APP_NAME` | `func-sbsub-dev` |

### 3 – Set up the federated credential in Tenant B

A **Tenant B administrator** must perform these steps (cannot be automated from
Tenant A):

1. Create an **App Registration** in Tenant B.
2. Add a **Federated Credential** on the App Registration:
   - **Issuer**: `https://login.microsoftonline.com/<TENANT_A_ID>/v2.0`
   - **Subject**: the `uamiPrincipalId` output from the Bicep deployment
     (this is the Object/Principal ID of the UAMI)
   - **Audience**: `api://AzureADTokenExchange`
3. Assign the App Registration's service principal the
   **Azure Service Bus Data Receiver** role on the Service Bus namespace
   (or narrower scope: topic/subscription).
4. Note the App Registration's **Client ID** and provide it as
   `CROSS_TENANT_APP_CLIENT_ID` in GitHub Variables.

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

After the first deployment, note the `uamiPrincipalId` output and use it to
configure the federated credential in Tenant B (step 3 above).

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

> **Note**: Cross-tenant auth requires a real UAMI, which is only available
> when running inside Azure.  For local testing you can replace
> `ManagedIdentityCredential` with `AzureCliCredential` if your CLI identity has
> been granted the necessary roles in both tenants.

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
| `CROSS_TENANT_SERVICE_BUS_NAMESPACE` | FQDN of the Service Bus (Tenant B) |
| `CROSS_TENANT_TOPIC_NAME` | Topic name |
| `CROSS_TENANT_SUBSCRIPTION_NAME` | Subscription name |
| `CROSS_TENANT_TENANT_ID` | Entra Tenant ID of Tenant B |
| `CROSS_TENANT_APP_CLIENT_ID` | App Registration Client ID in Tenant B |
| `USER_ASSIGNED_MI_CLIENT_ID` | Client ID of the UAMI in Tenant A |
| `STORAGE_ACCOUNT_NAME` | Storage account name (Tenant A) |
| `STORAGE_CONTAINER_NAME` | Blob container for received messages |
| `TIMER_SCHEDULE` | NCRONTAB (default: `0 */1 * * * *` = every minute) |
| `MAX_MESSAGE_BATCH_SIZE` | Max messages per invocation (default: `10`) |

---

## GitHub Copilot Coding Agent

This repository ships three specialist Copilot Coding Agents in
`.github/agents/` to facilitate "vibe coding":

| Agent | File | Purpose |
|---|---|---|
| Bicep Infrastructure | `bicep-infrastructure.md` | Author/review Bicep templates |
| Python Function | `python-function.md` | Author/review function code |
| CI/CD Workflow | `cicd-workflow.md` | Author/review GitHub Actions workflows |

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
