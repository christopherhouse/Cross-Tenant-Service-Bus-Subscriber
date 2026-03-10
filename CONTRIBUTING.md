# Contributing to Cross-Tenant Service Bus Subscriber

Thank you for your interest in contributing! This guide explains how to report
bugs, propose features, and submit pull requests.

---

## Code of conduct

This project follows the
[Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).
By participating you agree to abide by its terms.  Report unacceptable behavior
to the repository maintainers via GitHub's private reporting feature.

---

## Reporting bugs

Before filing a new bug, search
[existing issues](../../issues) to avoid duplicates.

Use the **Bug Report** issue template and include:
- A clear, concise description of the problem
- Steps to reproduce (minimal repro preferred)
- Expected vs actual behavior
- Environment details (Python version, Azure Functions Core Tools version, OS)
- Relevant log output — **redact any tenant IDs, client IDs, or namespace names**

---

## Suggesting features

Use the **Feature Request** issue template.  Describe the problem you are trying
to solve rather than jumping straight to the solution — this helps maintainers
understand the motivation and explore the best approach together.

---

## Development environment setup

### Prerequisites

| Tool | Minimum version | Install |
|---|---|---|
| Python | 3.11 | [python.org](https://www.python.org/downloads/) |
| Azure Functions Core Tools | v4 | [docs](https://learn.microsoft.com/azure/azure-functions/functions-run-local) |
| Azure CLI | latest | [docs](https://learn.microsoft.com/cli/azure/install-azure-cli) |
| Bicep CLI | latest | `az bicep install` |

### Fork and clone

```bash
# Fork the repo on GitHub, then:
git clone https://github.com/<your-username>/Cross-Tenant-Service-Bus-Subscriber.git
cd Cross-Tenant-Service-Bus-Subscriber
```

### Install Python dependencies

```bash
cd src/function_app
pip install -r requirements.txt
pip install pytest pytest-mock   # test extras
```

### Configure local settings

```bash
cp src/function_app/local.settings.json.template src/function_app/local.settings.json
# Edit local.settings.json — fill in your own dev/test values
# NEVER commit local.settings.json (it is in .gitignore)
```

### Start the function locally

```bash
cd src/function_app
func start
```

> **Note**: Cross-tenant Service Bus authentication requires a real User
> Assigned Managed Identity.  For local development you can stub out the
> credentials or use an Azure VM / Cloud Shell where a UAMI is available.

---

## Coding conventions

See `.github/copilot-instructions.md` for the full conventions reference.
Key highlights:

- **Python v2 programming model** — use `@app.timer_trigger(...)` decorators.
- **No hardcoded credentials** — all config via environment variables; use
  `_require_env()` / `_opt_env()`.
- **Type-annotate** all public functions.
- **Log** with the standard `logging` module, not `print`.
- **Bicep** — follow the Azure resource abbreviation guide; use `@description()`
  on every `param` and `output`; never store secrets in parameter files.

---

## Pull request process

1. **Branch naming**: `feat/<short-description>`, `fix/<short-description>`,
   `docs/<short-description>`, `chore/<short-description>`.
2. Keep PRs focused — one logical change per PR.
3. Update `CHANGELOG.md` under `[Unreleased]` with a summary of your change.
4. Update `README.md` if you change behavior, add settings, or change
   deployment steps.
5. Ensure all tests pass: `python -m pytest tests/ -v`.
6. If you added or changed Bicep: `az bicep build --file infra/main.bicep`.
7. Fill in the **Pull Request Template** checklist before requesting review.
8. At least one maintainer approval is required before merging.

### Commit message format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

[optional body]

[optional footer(s)]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`.

Examples:
```
feat(function): add dead-letter queue monitoring
fix(auth): handle token expiry in ClientAssertionCredential
docs(readme): add Tenant B setup screenshot
ci(deploy): pin azure/arm-deploy to v2
```

---

## Questions?

Open a [Discussion](../../discussions) for general questions and ideas.
Use Issues only for confirmed bugs and actionable feature requests.
