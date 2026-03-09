# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| `main` branch (latest) | ✅ Active |
| Older tags | ❌ Not supported |

Security fixes are applied to the `main` branch only.  We recommend always
running the latest version.

---

## Reporting a vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately using GitHub's built-in
[Private Vulnerability Reporting](../../security/advisories/new) feature.

Include as much of the following as possible:

- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept (PoC)
- Affected component(s): function code, Bicep templates, CI/CD workflows
- Any suggested mitigations

### Response SLA

| Step | Target |
|---|---|
| Acknowledge receipt | 3 business days |
| Initial assessment | 7 business days |
| Fix or mitigation published | Depends on severity (see below) |

**Severity guidance:**

| Severity | Target fix timeline |
|---|---|
| Critical (CVSS ≥ 9.0) | 7 days |
| High (CVSS 7.0–8.9) | 14 days |
| Medium / Low | Next scheduled release |

We will credit reporters in the release notes unless you prefer to remain
anonymous.

---

## Security design

This project is designed with a zero-secret posture:

| Concern | Mitigation |
|---|---|
| Azure credentials in code | Never stored — all auth via managed identities and OIDC |
| Cross-tenant Service Bus access | `ClientAssertionCredential` with federated credential; no client secret |
| Storage connection strings | Identity-based `AzureWebJobsStorage__accountName` configuration |
| CI/CD pipeline credentials | OIDC federated credential (no long-lived secrets in GitHub) |
| TLS | Minimum TLS 1.2 enforced on Function App; FTPS disabled |
| Blob storage | Public access disabled; RBAC-only access |

### Dependency security

Dependencies are pinned with minor-version ranges in `requirements.txt`.
Review and update regularly using:

```bash
pip list --outdated
```

Check advisories with `pip-audit`:

```bash
pip install pip-audit
pip-audit -r src/function_app/requirements.txt
```

---

## Out of scope

The following are outside this project's direct control and should be reported
to the appropriate vendor:

- Vulnerabilities in `azure-functions`, `azure-identity`, `azure-servicebus`,
  or `azure-storage-blob` packages → report to [Microsoft Security Response Center](https://msrc.microsoft.com/)
- Vulnerabilities in Azure infrastructure services (Service Bus, Storage, etc.)
  → report to [Microsoft Security Response Center](https://msrc.microsoft.com/)
