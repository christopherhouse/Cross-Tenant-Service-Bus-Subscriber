# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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

---

<!-- Releases will be added below this line -->

[Unreleased]: https://github.com/christopherhouse/Cross-Tenant-Service-Bus-Subscriber/compare/HEAD...HEAD
