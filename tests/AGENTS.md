<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-25 | Updated: 2026-04-25 -->

# tests

## Purpose
Automated pytest suite for the `bedrock_conversation` integration. Uses `pytest-homeassistant-custom-component` to simulate the Home Assistant runtime and mocks `boto3` so tests never touch real AWS. Invoked via `make test` (full coverage) or `make test-simple` (curated subset).

## Key Files

| File | Description |
|------|-------------|
| `conftest.py` | Shared fixtures. Provides `mock_setup_entry`, `mock_unload_entry`, and a **custom synchronous `hass`** MagicMock that intentionally overrides the autouse `hass` fixture from `pytest-homeassistant-custom-component` to avoid asyncio entanglement in simple tests. |
| `test_init.py` | Validates integration constants and the `HassServiceTool` schema/allowlists. |
| `test_bedrock_client.py` | Exercises the `DeviceInfo` dataclass and basic `BedrockClient` wiring. |
| `test_config_flow.py` | Tests `validate_aws_credentials` — asserts AWS error codes map to the correct HA form errors (`invalid_credentials`, `access_denied`, `cannot_connect`). |
| `test_utils.py` | Covers `closest_color` against known RGB inputs. |
| `test_system_prompt.py` | Validates `_generate_system_prompt` template substitution and Jinja rendering of the device list. |
| `test_device_context.py` | Verifies `_get_exposed_entities` / `DeviceInfo` output against a mocked entity registry. |
| `test_tool_calling.py` | Largest test file; covers the end-to-end tool-calling loop, Bedrock response parsing, and iteration limits. |

## For AI Agents

### Working In This Directory

- **Never make real AWS calls.** Every `boto3.client(...)` must be patched. The `hass` fixture in `conftest.py` is deliberately a MagicMock — tests here do not spin up a real HA instance.
- **The custom `hass` fixture overrides the autouse one.** If you add a test that needs the real async HA fixture from `pytest-homeassistant-custom-component`, override `hass` locally in that test module or use a differently-named fixture — don't delete `conftest.py`'s version.
- **Coverage target is `custom_components.bedrock_conversation`.** Tests that import from other paths won't contribute to coverage and won't gate `make release`.
- **`make test-simple` is the curated fast subset** (`test_bedrock_client.py`, `test_config_flow.py`, `test_init.py`, `test_utils.py`). `make release` uses this — it's the release gate. Broader tests (`test_tool_calling.py`, `test_system_prompt.py`, `test_device_context.py`) run under `make test` but not `make release`. Be aware which bucket your test lands in.
- **When adding a config key**: add a test in `test_init.py` or `test_config_flow.py` confirming the default and the options-flow schema entry.
- **When changing the tool-call loop**: update or extend `test_tool_calling.py` — that file is the regression net for the most stateful piece of code in the integration.

### Testing Requirements
- Use `pytest.mark.asyncio` for async tests.
- Mock at the `boto3.client(...)` boundary, not at the HTTP layer.
- Assert on structured results (`{"result": "success", ...}`) from `HassServiceTool.async_call` rather than free-text error messages.

### Common Patterns
- `AsyncMock` for awaitable methods on the `hass` mock; `MagicMock` for synchronous ones.
- Parametrize AWS error-code mappings in `test_config_flow.py` rather than duplicating cases.

## Dependencies

### Internal
- `custom_components.bedrock_conversation.*` — the code under test.

### External
- `pytest`
- `pytest-homeassistant-custom-component` — HA test harness, including the `hass` fixture this directory overrides.
- `unittest.mock` — `AsyncMock`, `MagicMock`, `patch`.

<!-- MANUAL: -->
