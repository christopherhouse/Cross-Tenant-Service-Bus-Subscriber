# Cross-Tenant Service Bus Subscriber

[![Deploy .NET Function](https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/actions/workflows/deploy-dotnet-function.yml/badge.svg)](https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/actions/workflows/deploy-dotnet-function.yml)
[![Deploy Infrastructure](https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/actions/workflows/deploy-infra.yml/badge.svg)](https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/actions/workflows/deploy-infra.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![.NET 10](https://img.shields.io/badge/.NET-10-512BD4.svg)](https://dotnet.microsoft.com/download/dotnet/10.0)
[![Azure Functions v4](https://img.shields.io/badge/Azure%20Functions-v4-blue)](https://learn.microsoft.com/azure/azure-functions/)

This repository demonstrates an **Azure Function (.NET 10, isolated worker
model)** that runs on a one-minute timer, polls a Service Bus topic
subscription hosted in a **separate Entra (Azure AD) tenant**, and writes
each received message payload as a JSON blob to Azure Blob Storage — all
without storing any secrets, using only Managed Identity and federated
credentials.

---

## Table of contents

- [Architecture](#architecture)
- [Authentication model](#authentication-model)
- [Repository structure](#repository-structure)
- [Key technologies](#key-technologies)
- [Prerequisites](#prerequisites)
- [One-time setup](#one-time-setup)
- [Deployment](#deployment)
- [Local development](#local-development)
- [Running tests](#running-tests)
- [Application settings reference](#application-settings-reference)
- [GitHub Actions variables and secrets](#github-actions-variables-and-secrets)
- [GitHub Copilot Coding Agent](#github-copilot-coding-agent)
- [Security notes](#security-notes)
- [Legacy Python implementation](#legacy-python-implementation)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Tenant A (subscriber tenant)                                  │
│                                                               │
│  ┌────────────────────────┐    ┌──────────────────────────┐  │
│  │  Azure Container       │    │  Storage Account         │  │
│  │  Registry (ACR)        │    │  /sb-messages/<date>/    │  │
│  └────────────┬───────────┘    └──────────────────────────┘  │
│    pull image │ (UAMI / AcrPull)              ▲              │
│               ▼                               │ write blobs  │
│  ┌────────────────────────────────────────────┴───────────┐  │
│  │  Azure Function (.NET 10, timer, every 1 min)          │  │
│  └─────────────────────────┬──────────────────────────────┘  │
│                             │ UAMI                            │
└─────────────────────────────┼────────────────────────────────┘
                              │  ManagedIdentityCredential
                              │  → federated token (api://AzureADTokenExchange)
                              │  → ClientAssertionCredential
                              │  → Tenant B token (Service Bus Data Receiver)
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ Tenant B (publisher tenant)                                   │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Service Bus Namespace                                 │    │
│  │  └─ Topic ─▶ Subscription                            │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

---

## Authentication model

Cross-tenant Service Bus access uses a three-step token-exchange chain
implemented in `CrossTenantCredentialFactory.cs`:

**Step 1 — Obtain a federated token from the UAMI (Tenant A)**

`ManagedIdentityCredential` calls the Azure Instance Metadata Service (IMDS)
on behalf of the User-Assigned Managed Identity (UAMI) in Tenant A.  The
token is requested with audience `api://AzureADTokenExchange`.  This produces
a short-lived JWT that asserts the identity of the UAMI.

**Step 2 — Exchange the federated token for a Tenant B access token**

`ClientAssertionCredential` presents the UAMI JWT as a *client assertion* to
Tenant B's token endpoint (`login.microsoftonline.com/<TENANT_B_ID>`).  Tenant
B validates the assertion against the **Federated Credential** configured on
the App Registration, then issues a Tenant B access token scoped to Azure
Service Bus (`https://servicebus.azure.net/.default`).

**Step 3 — Connect to Service Bus in Tenant B**

`ServiceBusClient` uses the Tenant B token to authenticate against the
Service Bus namespace in Tenant B.  The UAMI is never sent to Tenant B;
only the derived access token crosses the tenant boundary.

Same-tenant Blob Storage access uses `ManagedIdentityCredential` directly
(no federation needed — the UAMI already has `Storage Blob Data Contributor`
in Tenant A).

---

## Repository structure

```
.
├── src/
│   └── dotnet/                             ← PRIMARY C# implementation
│       ├── CrossTenantServiceBus.slnx      ← Solution file
│       ├── FunctionApp/
│       │   ├── FunctionApp.csproj
│       │   ├── Program.cs                  ← Host builder, DI registration
│       │   ├── EnvironmentConfiguration.cs ← Config helper (RequireEnv / OptionalEnv)
│       │   ├── SettingNames.cs             ← App setting name constants
│       │   ├── CrossTenantCredentialFactory.cs  ← UAMI → ClientAssertionCredential
│       │   ├── BlobMessageWriter.cs        ← Writes SB messages to blob as JSON
│       │   ├── AzureClientFactories.cs     ← Factory interfaces for testability
│       │   ├── ServiceBusSubscriberFunction.cs  ← Timer trigger function
│       │   ├── host.json
│       │   ├── local.settings.json.template
│       │   └── Dockerfile                  ← Multi-stage .NET 10 build
│       └── FunctionApp.Tests/
│           ├── FunctionApp.Tests.csproj
│           ├── EnvironmentConfigurationTests.cs
│           ├── CrossTenantCredentialFactoryTests.cs
│           ├── BlobMessageWriterTests.cs
│           └── ServiceBusSubscriberFunctionTests.cs
├── infra/                                  ← Azure Bicep infrastructure
│   ├── main.bicep
│   ├── main.bicepparam
│   └── modules/
│       ├── user-assigned-identity.bicep
│       ├── storage-account.bicep
│       ├── app-service-plan.bicep
│       ├── function-app.bicep
│       ├── container-registry.bicep        ← ACR (Basic SKU) + AcrPull role
│       ├── log-analytics-workspace.bicep
│       └── app-insights.bicep
├── .github/
│   ├── copilot-instructions.md             ← Copilot Coding Agent repo context
│   ├── agents/
│   │   ├── bicep-infrastructure.md         ← Bicep specialist agent
│   │   ├── cicd-workflow.md                ← CI/CD specialist agent
│   │   ├── documentation.md               ← Documentation specialist agent
│   │   └── python-function.md             ← Python specialist agent (legacy)
│   └── workflows/
│       ├── deploy-dotnet-function.yml      ← .NET function build & deploy
│       ├── deploy-infra.yml                ← Bicep deployment workflow
│       └── deploy-function.yml            ← Legacy Python function workflow
├── docs/
│   └── python/
│       └── README.md                       ← Legacy Python implementation docs
└── tests/                                  ← Legacy Python unit tests
    ├── conftest.py
    └── test_function_app.py
```

---

## Key technologies

| Technology | Version / Details |
|---|---|
| .NET | 10 (isolated worker model) |
| Azure Functions | v4 |
| Microsoft.Azure.Functions.Worker | 2.51.0 |
| Azure.Identity | 1.18.0 — `ClientAssertionCredential` for cross-tenant auth |
| Azure.Messaging.ServiceBus | 7.20.1 |
| Azure.Storage.Blobs | 12.27.0 |
| Docker | Multi-stage container build; CI/CD uses ACR Tasks |
| Bicep | Latest — deployed via `deploy-infra.yml` |
| GitHub Actions | OIDC / federated credential workflow authentication |

---

## Prerequisites

| Tool | Minimum version | Install |
|---|---|---|
| .NET SDK | 10.0 | [dotnet.microsoft.com](https://dotnet.microsoft.com/download/dotnet/10.0) |
| Azure CLI | Latest | [learn.microsoft.com/cli/azure/install-azure-cli](https://learn.microsoft.com/cli/azure/install-azure-cli) |
| Bicep CLI | Latest | `az bicep install` |
| Azure Functions Core Tools | v4 | [learn.microsoft.com/azure/azure-functions/functions-run-local](https://learn.microsoft.com/azure/azure-functions/functions-run-local) |
| Docker | Latest | Optional — for local container builds; CI/CD uses ACR Tasks |

---

## One-time setup

### Tenant A: provision a service principal for GitHub Actions

This service principal is used **only by the CI/CD workflows** to deploy
infrastructure and the function container.

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

| Field | Value |
|---|---|
| Issuer | `https://token.actions.githubusercontent.com` |
| Subject | `repo:<org>/<repo>:environment:<env-name>` |
| Audience | `api://AzureADTokenExchange` |

### Tenant B: grant the function access to Service Bus

Because the App Registration and federated credential live in Tenant B, a
**Tenant B administrator** must complete these steps manually.

**Step 1 — Create an App Registration in Tenant B.**

In the Azure portal for Tenant B, create a new App Registration (the name is
arbitrary, e.g. `app-sbsub-cross-tenant`).

**Step 2 — Add a Federated Credential on the App Registration.**

Navigate to the App Registration → **Certificates & secrets** →
**Federated credentials** → **Add credential**.

| Field | Value |
|---|---|
| Scenario | Other issuer |
| Issuer | `https://login.microsoftonline.com/<TENANT_A_ID>/v2.0` |
| Subject identifier | Object (Principal) ID of the UAMI (Bicep output: `uamiPrincipalId`) |
| Audience | `api://AzureADTokenExchange` |

> **Note**: The subject is the UAMI's **Object (Principal) ID**, not its
> Client ID.  The Bicep deployment outputs this value as `uamiPrincipalId`.

**Step 3 — Assign the Service Bus Data Receiver role.**

Assign the App Registration's service principal (Enterprise Application) the
**Azure Service Bus Data Receiver** RBAC role on the Tenant B namespace:

```bash
az role assignment create \
  --assignee <app-registration-service-principal-object-id> \
  --role "Azure Service Bus Data Receiver" \
  --scope /subscriptions/<tenant-b-subscription-id>/resourceGroups/<rg>/providers/Microsoft.ServiceBus/namespaces/<namespace>
```

**Step 4 — Note the App Registration Client ID.**

Record the App Registration's **Client ID** and supply it as
`CROSS_TENANT_APP_CLIENT_ID` in application settings and GitHub Actions
variables.

---

## Deployment

### Deploy infrastructure

Push a change to `infra/**` on `main` to trigger the
`.github/workflows/deploy-infra.yml` workflow automatically, or run manually:

```bash
az deployment group create \
  --resource-group <rg-name> \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam
```

After the first deployment, note the `uamiPrincipalId` output.  Use it as the
federated credential subject when completing the Tenant B setup above.

### Deploy the function

Push a change to `src/dotnet/**` on `main` to trigger
`.github/workflows/deploy-dotnet-function.yml` automatically.  The workflow:

1. Restores NuGet packages.
2. Runs all unit tests.
3. Builds the container image inside ACR Tasks (`az acr build`) — no local
   Docker daemon required on the runner.
4. Tags the image with the full commit SHA for traceability.
5. Updates the Function App to pull the new image.

To deploy manually:

```bash
ACR_NAME="<acr-name>"
IMAGE_NAME="func-<workload-name>-<environment-name>-dotnet"
RG_NAME="<resource-group-name>"
FUNC_APP_NAME="<function-app-name>"

# 1. Build and push the container image via ACR Tasks
az acr build \
  --registry "$ACR_NAME" \
  --image "$IMAGE_NAME:latest" \
  --file src/dotnet/FunctionApp/Dockerfile \
  src/dotnet/FunctionApp

# 2. Point the Function App at the new image
az functionapp config container set \
  --resource-group "$RG_NAME" \
  --name "$FUNC_APP_NAME" \
  --image "$ACR_NAME.azurecr.io/$IMAGE_NAME:latest"
```

---

## Local development

### Option A — Azure Functions Core Tools (`func start`)

```bash
# 1. Copy the settings template
cp src/dotnet/FunctionApp/local.settings.json.template \
   src/dotnet/FunctionApp/local.settings.json

# 2. Edit local.settings.json and fill in all placeholder values

# 3. Start the function locally
cd src/dotnet/FunctionApp
func start
```

> **Note**: The UAMI is only available when running inside Azure.
> Cross-tenant authentication requires a real UAMI, so you must configure the
> federated credential in Tenant B even for local test runs.

### Option B — Docker

```bash
# 1. Build the container image locally
docker build \
  -f src/dotnet/FunctionApp/Dockerfile \
  -t func-sbsub-dotnet-local \
  src/dotnet/FunctionApp

# 2. Run the container, passing settings as environment variables
docker run -p 7071:80 \
  -e CROSS_TENANT_SERVICE_BUS_NAMESPACE=<value> \
  -e CROSS_TENANT_TENANT_ID=<value> \
  -e CROSS_TENANT_APP_CLIENT_ID=<value> \
  -e CROSS_TENANT_TOPIC_NAME=<value> \
  -e CROSS_TENANT_SUBSCRIPTION_NAME=<value> \
  -e USER_ASSIGNED_MI_CLIENT_ID=<value> \
  -e STORAGE_ACCOUNT_NAME=<value> \
  -e STORAGE_CONTAINER_NAME=<value> \
  func-sbsub-dotnet-local
```

> **Note**: Replace each `<value>` with a real setting.  Never commit
> environment-variable files that contain real credentials.

---

## Running tests

```bash
dotnet test src/dotnet/CrossTenantServiceBus.slnx
```

The test suite produces output similar to:

```
Passed!  - Failed: 0, Passed: N, Skipped: 0, Total: N
```

To run with verbose output:

```bash
dotnet test src/dotnet/CrossTenantServiceBus.slnx --logger "console;verbosity=detailed"
```

---

## Application settings reference

| Setting | Required | Description |
|---|---|---|
| `CROSS_TENANT_SERVICE_BUS_NAMESPACE` | ✅ | FQDN of the Service Bus namespace in Tenant B, e.g. `mybus.servicebus.windows.net` |
| `CROSS_TENANT_TENANT_ID` | ✅ | Entra Tenant ID of Tenant B |
| `CROSS_TENANT_APP_CLIENT_ID` | ✅ | Client ID of the multitenant App Registration in Tenant B |
| `CROSS_TENANT_TOPIC_NAME` | ✅ | Service Bus topic name |
| `CROSS_TENANT_SUBSCRIPTION_NAME` | ✅ | Service Bus subscription name |
| `USER_ASSIGNED_MI_CLIENT_ID` | ✅ | Client ID of the UAMI in Tenant A |
| `STORAGE_ACCOUNT_NAME` | ✅ | Storage account name in Tenant A |
| `STORAGE_CONTAINER_NAME` | ✅ | Blob container name for received messages |
| `TIMER_SCHEDULE` | ⬜ | NCRONTAB schedule (default: `0 */1 * * * *`) |
| `SB_MAX_MESSAGE_COUNT` | ⬜ | Max messages per poll (default: `100`) |
| `SB_MAX_WAIT_TIME_SECONDS` | ⬜ | Max wait time per poll in seconds (default: `5`) |

---

## GitHub Actions variables and secrets

Configure these at the repository or environment level in **Settings →
Secrets and variables → Actions**.

### Secrets

| Secret | Description |
|---|---|
| `AZURE_CLIENT_ID` | Client ID of the GitHub Actions service principal (OIDC) |
| `AZURE_TENANT_ID` | Entra Tenant ID of Tenant A |
| `AZURE_SUBSCRIPTION_ID` | Azure Subscription ID in Tenant A |

### Variables

| Variable | Used by | Example | Description |
|---|---|---|---|
| `AZURE_RG_NAME` | Both workflows | `rg-sbsub-dev` | Target resource group |
| `AZURE_LOCATION` | `deploy-infra.yml` | `eastus` | Azure region for the resource group |
| `ENVIRONMENT_NAME` | Both workflows | `dev` | Deployment environment label |
| `WORKLOAD_NAME` | Both workflows | `sbsub` | Short prefix; derives image name |
| `ACR_NAME` | `deploy-dotnet-function.yml` | `crsbsubdev` | Azure Container Registry name (output of infra deployment) |
| `AZURE_DOTNET_FUNCTION_APP_NAME` | `deploy-dotnet-function.yml` | `func-sbsub-dev-dotnet` | Name of the .NET Function App |
| `CROSS_TENANT_SB_NAMESPACE` | `deploy-infra.yml` | `mybus.servicebus.windows.net` | FQDN of the Service Bus namespace in Tenant B |
| `CROSS_TENANT_TENANT_ID` | `deploy-infra.yml` | `<tenant-b-id>` | Entra Tenant ID of Tenant B |
| `CROSS_TENANT_APP_CLIENT_ID` | `deploy-infra.yml` | `<client-id>` | Client ID of the App Registration in Tenant B |
| `CROSS_TENANT_TOPIC_NAME` | `deploy-infra.yml` | `orders` | Service Bus topic name |
| `CROSS_TENANT_SUBSCRIPTION_NAME` | `deploy-infra.yml` | `fn-subscriber` | Service Bus subscription name |

---

## GitHub Copilot Coding Agent

This repository ships four specialist Copilot Coding Agents in `.github/agents/`
to support AI-assisted development:

| Agent | File | Purpose |
|---|---|---|
| Bicep Infrastructure | `bicep-infrastructure.md` | Author and review Bicep infrastructure templates |
| CI/CD Workflow | `cicd-workflow.md` | Author and review GitHub Actions workflows |
| Documentation | `documentation.md` | Maintain README, CHANGELOG, and other docs |
| Python Function | `python-function.md` | Author and review the legacy Python function |

Global repository context and conventions are defined in
`.github/copilot-instructions.md`.

---

## Security notes

- **No secrets in code or Bicep**: all credentials flow through Managed
  Identity and OIDC federated credentials.
- Storage access uses identity-based `AzureWebJobsStorage__accountName`
  (no connection string).
- ACR pull uses UAMI-based managed identity (`acrUseManagedIdentityCreds: true`);
  no registry credentials are stored in app settings or source code.
- FTPS is disabled; minimum TLS 1.2 is enforced on the Function App.
- Blob container public access is disabled.
- GitHub Actions authenticates to Azure via OIDC — no long-lived client
  secrets are stored in GitHub.

---

## Legacy Python implementation

A legacy **Python** implementation is preserved for reference in
[`docs/python/README.md`](docs/python/README.md).  The Python implementation
follows the same cross-tenant authentication pattern but uses the Python Azure
SDK.  New development should target the C# .NET 10 implementation.

---

## Contributing

Contributions are welcome.  Read [CONTRIBUTING.md](CONTRIBUTING.md) for
coding conventions, branch naming, commit message format, and the pull request
process.

---

## Security

To report a security vulnerability, follow the process described in
[SECURITY.md](SECURITY.md).  Do not open a public issue for security concerns.

---

## License

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
