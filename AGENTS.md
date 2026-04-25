<!-- Generated: 2026-04-25 | Updated: 2026-04-25 -->

# homeassistant-aws-bedrock-conversation-agent

## Purpose
A Home Assistant **custom integration** that exposes AWS Bedrock foundation models (Anthropic Claude, Meta Llama, Mistral) as a conversation agent with device control through Home Assistant's LLM/tool-calling system. The integration is distributed via HACS and installed into a Home Assistant instance's `config/custom_components/` directory.

## Key Files

| File | Description |
|------|-------------|
| `Makefile` | Build automation: `venv`, `deps`, `test`, `lint`, `format`, `typecheck`, `release`. Entry point for all dev workflows. |
| `pyproject.toml` | Python project metadata and tool configuration. |
| `pytest.ini` | Pytest configuration. |
| `requirements-dev.txt` | Developer tooling (ruff, black, isort, mypy, flake8). |
| `requirements-test.txt` | Test-only dependencies (pytest, pytest-homeassistant-custom-component). |
| `run_tests.sh` | Alternative test runner that installs deps into the current interpreter. |
| `test_bedrock.py` | Manual smoke test that hits real AWS Bedrock using env-var credentials. Not part of the automated suite. |
| `hacs.json` | HACS integration metadata (name, country, render_readme). |
| `repository.json` | Repository-level metadata. |
| `manifest.json` (in `custom_components/bedrock_conversation/`) | Single source of truth for the release version. |
| `apparmor.txt` | AppArmor profile for add-on style deployment contexts. |
| `README.md` | Top-level readme; points end users at the integration-level README. |
| `INSTALL.md` | User-facing install instructions. |
| `DEVELOPMENT.md` | Developer workflow reference (maps to Makefile targets). |
| `TESTING_GUIDE.md` | Testing conventions and examples. |
| `WARP.md` | Architectural reference originally written for the WARP agent; still the most complete in-repo design doc. |
| `CHANGELOG.md` | Release history. |
| `LICENSE` | MIT license. |
| `icon.png`, `logo.png` | Integration branding assets. |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `custom_components/` | Home Assistant custom component root (see `custom_components/AGENTS.md`). |
| `tests/` | Pytest-based test suite (see `tests/AGENTS.md`). |
| `translations/` | Service-level translations (see `translations/AGENTS.md`). |
| `.github/` | GitHub Actions workflows and repo metadata. |
| `.omc/` | oh-my-claudecode session state (agent-generated; not shipped). |

## For AI Agents

### Working In This Directory
- **Never bypass the Makefile** when installing deps or running tests — `make test` creates `.venv/`, installs pinned requirements, and runs pytest with coverage. Running `pytest` directly from a global interpreter will miss `pytest-homeassistant-custom-component`.
- **Version bumps happen in `custom_components/bedrock_conversation/manifest.json` only.** `make version` and `make release` read from that file; there is no other version string.
- `make release` refuses to run with a dirty working tree or a pre-existing tag. Resolve those before invoking it; do not `--force` tags.
- **WARP.md is the canonical architecture doc.** If you update the integration's high-level design, update WARP.md. `README.md` at the root intentionally stays short and delegates to `custom_components/bedrock_conversation/README.md` for end-user docs.
- `test_bedrock.py` at the root hits real AWS — do not invoke it in CI or without credentials intentionally provided.

### Testing Requirements
- `make test` runs the full suite with coverage (`htmlcov/index.html`, term-missing report). This is the gate for `make release`.
- `make test-simple` runs a curated subset (client, config flow, init, utils) — use when iterating and the full async-heavy tests are noise.
- Tests must not make real AWS calls; mock `boto3` at the client boundary.

### Common Patterns
- Build targets depend on `deps`, which depends on `venv`. Any target that needs the venv should declare that dependency rather than assume the venv exists.
- `make format` runs `black .` and `isort .` over the entire repo, including tests.
- Linting is Ruff-driven (`make lint` → `ruff check .`). Configure Ruff via `pyproject.toml`.

## Dependencies

### External
- `boto3 >= 1.35.0` — AWS Bedrock client (declared in `manifest.json` requirements so Home Assistant installs it at runtime).
- `webcolors >= 24.8.0` — CSS3 color-name matching for human-readable device attributes.
- `pytest`, `pytest-homeassistant-custom-component` — Test harness.
- `ruff`, `black`, `isort`, `flake8`, `mypy` — Code quality tools.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
