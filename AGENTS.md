<!-- Generated: 2026-04-25 | Updated: 2026-04-26 -->

# homeassistant-bedrock-ha-agent

## Purpose
A Home Assistant **custom integration** that turns AWS Bedrock foundation models (Anthropic Claude, Meta Llama, Mistral) into a full conversation agent for HA. It supports device control, streaming responses, token-usage sensors, Amazon Polly TTS, Amazon Transcribe STT, camera-snapshot vision input, and — when explicitly enabled — two opt-in tool suites: approval-gated natural-language editing of automations/scripts/scenes/helpers/Lovelace/registries (`CONF_ENABLE_CONFIG_EDITING`, v1.1.0+), and a diagnostics & control suite for log diving, state/history reads, broader service calls with per-service classification, and lifecycle operations like integration reload and entity enable/disable (`CONF_ENABLE_DIAGNOSTICS`, v1.2.0+). Distributed via HACS and installed into a Home Assistant instance's `config/custom_components/` directory.

## Key Files

| File | Description |
|------|-------------|
| `Makefile` | Build automation: `venv`, `deps`, `test`, `test-simple`, `lint`, `format`, `typecheck`, `release`. Entry point for all dev workflows. |
| `pyproject.toml` | Python project metadata and tool configuration (ruff, black, isort, mypy). |
| `pytest.ini` | Pytest configuration (asyncio mode, coverage target). |
| `requirements-dev.txt` | Developer tooling (ruff, black, isort, mypy, flake8). |
| `requirements-test.txt` | Test-only dependencies pinned for HA 2025.6.0+ (pytest-homeassistant-custom-component, hassil, home-assistant-intents, PyTurboJPEG, av). |
| `run_tests.sh` | Alternative test runner that installs deps into the current interpreter. |
| `test_bedrock.py` | Manual smoke test that hits real AWS Bedrock using env-var credentials. Not part of the automated suite; do not run in CI. |
| `hacs.json` | HACS integration metadata (name, country, render_readme). |
| `repository.json` | Repository-level metadata. |
| `apparmor.txt` | AppArmor profile for add-on style deployment contexts. |
| `README.md` | Primary user-facing documentation: install, AWS setup, config options, troubleshooting, config-editing opt-in. |
| `DEVELOPMENT.md` | Contributor guide: repo layout, Makefile targets, release workflow. |
| `CHANGELOG.md` | Release history (keep-a-changelog style). `v1.1.0` = config-editing port; `v1.1.1` through current track post-port field fixes. |
| `LICENSE` | MIT license. |
| `icon.png`, `logo.png` | Integration branding assets. |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `custom_components/` | Home Assistant custom component root (see `custom_components/AGENTS.md`). |
| `tests/` | Pytest-based test suite — config-editing ACs, tool base, transports, approval flow (see `tests/AGENTS.md`). |
| `translations/` | Service-level translations consumed by HA's service registry (see `translations/AGENTS.md`). |
| `.github/` | GitHub Actions workflows (Python 3.13 matrix, libturbojpeg0-dev apt install for PyTurboJPEG) and repo metadata. |

## For AI Agents

### Working In This Directory
- **Never bypass the Makefile** when installing deps or running tests — `make test` creates `.venv/`, installs pinned requirements, and runs pytest with coverage. Running `pytest` directly from a global interpreter will miss `pytest-homeassistant-custom-component` and the HA 2025.6+ pin.
- **Version bumps happen in `custom_components/bedrock_ha_agent/manifest.json` only.** `make version` and `make release` read from that file; there is no other version string. CHANGELOG.md gets a matching entry.
- `make release` refuses to run with a dirty working tree or a pre-existing tag. Resolve those before invoking it; do not `--force` tags.
- **AGENTS.md files are the canonical architecture reference.** Keep implementation detail out of `README.md` (end-user-facing) and in here instead.
- `test_bedrock.py` at the root hits real AWS — do not invoke it in CI or without credentials intentionally provided.
- The integration domain is `bedrock_ha_agent`. The LLM API id is `bedrock_ha_agent_services`. Do not rename either without coordinating a breaking-change release.

### Testing Requirements
- `make test` runs the full suite with coverage (`htmlcov/index.html`, term-missing report). This is the gate for `make release`.
- `make test-simple` runs a curated fast subset (client, config flow, init, utils) — use when iterating and the full async/config-editing tests are noise.
- Tests must not make real AWS calls; mock `boto3` at the client boundary.
- Config-editing tests mock at the `ha_client/` transport boundary, not at the filesystem.

### Common Patterns
- Build targets depend on `deps`, which depends on `venv`. Any target that needs the venv should declare that dependency rather than assume the venv exists.
- `make format` runs `black .` and `isort .` over the entire repo, including tests.
- Linting is Ruff-driven (`make lint` → `ruff check .`). Configure Ruff via `pyproject.toml`.

### Debugging live Home Assistant errors
When a user reports an "Unexpected error during intent recognition" or similar wrapper error, **always prefer the real traceback from HA over guesswork**. If `hass-cli` is on the PATH and the user's shell has exported `HASS_SERVER` + `HASS_TOKEN` (check with `env | grep HASS_`), the integration's errors can be read directly via the HA WebSocket API without touching their config files or filesystem:

```python
import asyncio, aiohttp, os

async def fetch_errors():
    token = os.environ["HASS_TOKEN"]
    url = os.environ["HASS_SERVER"].rstrip("/").replace("http", "ws", 1) + "/api/websocket"
    async with aiohttp.ClientSession() as s, s.ws_connect(url) as ws:
        await ws.receive_json()  # auth_required
        await ws.send_json({"type": "auth", "access_token": token})
        await ws.receive_json()  # auth_ok
        await ws.send_json({"id": 1, "type": "system_log/list"})
        resp = await ws.receive_json()
        for r in resp.get("result", []):
            if r.get("level") == "ERROR" and "bedrock_ha_agent" in (r.get("exception") or ""):
                print(r.get("exception"))

asyncio.run(fetch_errors())
```

Run via `.venv/bin/python <<'PY' ... PY` so `aiohttp` is available. `hass-cli raw ws system_log/list` is not reliable on Python 3.13+; the direct WebSocket call is more portable. Never hardcode a token or server URL in committed files; always read them from the user's environment.

## Dependencies

### External
- `boto3 >= 1.35.0` — AWS Bedrock client (declared in `manifest.json` requirements so HA installs it at runtime).
- `webcolors >= 24.8.0` — CSS3 color-name matching for human-readable device attributes.
- `amazon-transcribe >= 0.6.2` — async streaming STT.
- `pytest`, `pytest-homeassistant-custom-component` — Test harness.
- `ruff`, `black`, `isort`, `flake8`, `mypy` — Code quality tools.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
