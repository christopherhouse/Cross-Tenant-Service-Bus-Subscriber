# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- `src/function_app/Dockerfile`: builds the Azure Function as a container image
  using `mcr.microsoft.com/azure-functions/python:4-python3.13` as the base
  image.
- `src/function_app/.dockerignore`: excludes unnecessary files (local settings,
  virtual environments, `__pycache__`, etc.) from the Docker build context.
- `infra/modules/container-registry.bicep`: provisions an Azure Container
  Registry (Basic SKU) and grants the UAMI the `AcrPull` role via a role
  assignment.

### Changed
- **App Service Plan** migrated from Consumption (Y1 / Dynamic) to Elastic
  Premium (EP1 / ElasticPremium).  Custom Docker container images require a
  dedicated or premium plan; Consumption plans do not support them.
- **Function App** deployment method changed from zip-deploy + `pip install
  --target` to a Docker container image pulled from Azure Container Registry.
  `linuxFxVersion` is now `DOCKER|<acr-login-server>/<image>:latest` instead
  of `Python|3.13`.  Added `DOCKER_REGISTRY_SERVER_URL` app setting and
  removed `SCM_DO_BUILD_DURING_DEPLOYMENT`.
- **`infra/main.bicep`** now deploys the ACR module and passes ACR outputs
  (`acrName`, `acrLoginServer`) to the Function App module.  The ACR name is
  derived as `cr<workloadName><environmentName>` (e.g. `crsbsubdev`); the image
  name is derived as `func-<workloadName>-<environmentName>` (e.g.
  `func-sbsub-dev`).
- **`deploy-function.yml`** CI/CD workflow replaced `pip install --target` and
  `Azure/functions-action` zip-deploy steps with:
  - `az acr build` (ACR Tasks) — builds and pushes the container image without
    requiring a local Docker daemon on the runner.
  - `az functionapp config container set` — updates the running Function App
    to pull the new image (tagged with the commit SHA for traceability).

### Security
- ACR pull authentication uses UAMI-based managed identity
  (`acrUseManagedIdentityCreds: true`, `acrUserManagedIdentityID` set to the
  UAMI client ID).  No registry credentials are stored in app settings or
  source code.

---

## [0.1.0] - Initial release

### Added
- Initial project scaffold with full cross-tenant Service Bus subscriber solution.
- Python Azure Function (v2 programming model) with timer trigger that polls a
  Service Bus topic subscription in a remote Entra tenant using
  `ClientAssertionCredential` (federated credential / UAMI).
- Message payloads written as JSON blobs to Azure Blob Storage
  (`YYYY/MM/DD/<message-id>.json`).
- Bicep infrastructure templates for Tenant A: User Assigned MI, Storage Account,
  App Service Plan (Consumption), Function App, Log Analytics, Application Insights.
- Identity-based `AzureWebJobsStorage` configuration (no connection strings).
- GitHub Actions CI/CD workflows with OIDC authentication:
  - `deploy-infra.yml` — Bicep deployment (triggers on `infra/**` changes).
  - `deploy-function.yml` — function code deployment (triggers on `src/**` changes).
- GitHub Copilot Coding Agent artifacts:
  - `.github/copilot-instructions.md` — repo-wide context and conventions.
  - `.github/agents/bicep-infrastructure.md` — Bicep specialist agent.
  - `.github/agents/python-function.md` — Python function specialist agent.
  - `.github/agents/cicd-workflow.md` — CI/CD specialist agent.
  - `.github/agents/documentation.md` — documentation specialist agent.
- `pytest` unit tests covering happy path, error/abandon path, empty batch,
  past-due timer, and mixed success/failure scenarios.
- `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, issue templates, and PR
  template for open-source community health.

### Fixed
- Replaced the Service Bus trigger with a timer trigger and implemented
  cross-tenant authentication using `ClientAssertionCredential` in the Python
  function code. The previous implementation used the runtime
  `managedidentityasfederatedidentity` credential which failed to perform the
  UAMI→Tenant B token exchange, causing `InvalidIssuer: Token issuer is
  invalid` errors when connecting to the Service Bus namespace in Tenant B.
- Removed the six `SERVICE_BUS_CONNECTION__*` runtime binding app settings
  (`credential`, `azureCloud`, `clientId`, `tenantId`,
  `managedIdentityClientId`, `fullyQualifiedNamespace`) and replaced them with
  three clean `CROSS_TENANT_*` env vars consumed directly by the Python code:
  `CROSS_TENANT_SERVICE_BUS_NAMESPACE`, `CROSS_TENANT_TENANT_ID`,
  `CROSS_TENANT_APP_CLIENT_ID`.
- Added `azure-servicebus>=7.12.0,<8.0.0` to `requirements.txt`.

---

[Unreleased]: https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/releases/tag/v0.1.0
