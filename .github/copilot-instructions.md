# GitHub Copilot – Repository Instructions

## Project overview

This repository contains a **Cross-Tenant Service Bus Subscriber** solution.  An
Azure Function (Python, v2 programming model) running in **Tenant A** polls a
Service Bus topic subscription that lives in a separate **Tenant B** Entra
tenant, and writes every received message payload as a JSON blob to an Azure
Storage Account in Tenant A.

## Repository structure

```
.
├── src/
│   └── function_app/          # Azure Function source code
│       ├── Dockerfile                      # Container image definition
│       ├── .dockerignore                   # Docker build context exclusions
│       ├── function_app.py    # Main function (timer trigger, cross-tenant auth, blob write)
│       ├── host.json          # Azure Functions host configuration
│       ├── requirements.txt   # Python dependencies
│       └── local.settings.json.template  # Local dev settings (never commit the real file)
├── infra/
│   ├── main.bicep             # Root orchestration Bicep template
│   ├── main.bicepparam        # Parameter file (fill in Tenant B values)
│   └── modules/
│       ├── user-assigned-identity.bicep
│       ├── storage-account.bicep
│       ├── app-service-plan.bicep
│       ├── function-app.bicep
│       ├── container-registry.bicep        # ACR (Basic SKU) + AcrPull role
│       ├── log-analytics-workspace.bicep
│       └── app-insights.bicep
├── .github/
│   ├── copilot-instructions.md   ← you are here
│   ├── agents/                   # Custom Copilot agents
│   │   ├── bicep-infrastructure.md
│   │   ├── python-function.md
│   │   ├── cicd-workflow.md
│   │   └── documentation.md
│   └── workflows/
│       ├── deploy-infra.yml      # Bicep deployment workflow
│       └── deploy-function.yml   # Container build and deployment workflow
└── tests/                    # Python unit tests (pytest)
```

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

## Key technologies

| Technology | Version / Notes |
|---|---|
| Python | 3.13 |
| Azure Functions | v4, Python v2 programming model |
| azure-functions | ≥ 1.21 |
| azure-identity | ≥ 1.17 (ClientAssertionCredential for cross-tenant auth) |
| azure-servicebus | ≥ 7.12 |
| azure-storage-blob | ≥ 12.22 |
| Docker | Container image (`mcr.microsoft.com/azure-functions/python:4-python3.13`); CI/CD uses ACR Tasks |
| Bicep | Latest (deployed via GitHub Actions) |
| GitHub Actions | OIDC / federated credential workflow auth |

## Coding conventions

### Python
- Use the **Azure Functions Python v2 programming model** (`@app.timer_trigger`, etc.).
- Use `azure.identity.ClientAssertionCredential` + `ManagedIdentityCredential` for
  cross-tenant authentication; never hard-code secrets.
- All configuration comes from **environment variables**; use `_require_env()` for
  mandatory vars and `_opt_env()` for optional ones with defaults.
- Log with the standard `logging` module (not `print`).
- Type-annotate all public functions.
- Keep functions focused and small; separate concerns (credential factories vs.
  message processing vs. Function entry point).

### Bicep
- All modules live under `infra/modules/`.
- Name resources following the [Azure naming convention](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/azure-best-practices/resource-naming):
  `<resource-type-abbreviation>-<workload>-<environment>`.
- Prefer **identity-based auth** (UAMI + RBAC role assignments) over connection
  strings wherever possible.
- Never store secrets in Bicep parameter files; pass sensitive values as GitHub
  Actions secrets at deployment time.
- Use `@description()` decorators on all `param` and `output` declarations.

### GitHub Actions
- Use **OIDC federated credentials** for Azure login (no client secrets stored).
- Workflows are path-scoped so only relevant code triggers each workflow.
- Store environment-specific config in **GitHub Actions Variables**; store secrets
  in **GitHub Actions Secrets**.

## Local development setup

### Option A — Azure Functions Core Tools

1. Install [Azure Functions Core Tools v4](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local).
2. Copy `src/function_app/local.settings.json.template` →
   `src/function_app/local.settings.json` and fill in values.
3. `cd src/function_app && pip install -r requirements.txt`
4. `func start`

### Option B — Docker

1. Extract settings to a `.env` file:
   `jq -r '.Values | to_entries[] | "\(.key)=\(.value)"' src/function_app/local.settings.json > src/function_app/.env`
2. `docker build -t func-sbsub-local src/function_app/`
3. `docker run -p 7071:80 --env-file src/function_app/.env func-sbsub-local`

> **Note**: Cross-tenant Service Bus auth requires a real UAMI; use
> `DefaultAzureCredential` locally only if your developer account has been
> granted Service Bus Receiver + Blob Contributor in both tenants.

## Manual Tenant B setup (one-time, outside automation)

Because the service principal and federated credential live in Tenant B, they
cannot be provisioned by Bicep in Tenant A.  A Tenant B administrator must:

1. Create an **App Registration** in Tenant B.
2. Add a **Federated Credential** on that App Registration:
   - Issuer: `https://login.microsoftonline.com/<TENANT_A_ID>/v2.0`
   - Subject: the **Object (principal) ID** of the UAMI (output by Bicep:
     `uamiPrincipalId`)
   - Audience: `api://AzureADTokenExchange`
3. Assign the App Registration's service principal the
   **Azure Service Bus Data Receiver** role on the Service Bus namespace
   (or topic/subscription scope).
4. Note the App Registration's **Client ID** and provide it as
   `crossTenantAppClientId` / `CROSS_TENANT_APP_CLIENT_ID`.

## Testing

- Unit tests live in `tests/` and use **pytest** with **pytest-mock**.
- Mock `ManagedIdentityCredential`, `ClientAssertionCredential`, and the
  `ServiceBusClient` / `BlobServiceClient` using `unittest.mock.patch`.
- Run locally: `python -m pytest tests/ -v`
