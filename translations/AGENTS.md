<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-25 | Updated: 2026-04-25 -->

# translations

## Purpose
Service-description translations — the human-readable `name` and `description` strings Home Assistant shows in Developer Tools → Services and in the YAML editor for any services this integration might register. Distinct from the UI config-flow translations, which live at `custom_components/bedrock_conversation/translations/`.

## Key Files

| File | Description |
|------|-------------|
| `en.yaml` | English service-description strings for configuration fields (`aws_region`, `model_id`, `aws_access_key_id`, `aws_secret_access_key`, `temperature`, `max_tokens`, `aws_session_token`). YAML, not JSON. |

## For AI Agents

### Working In This Directory

- **Do not confuse this directory with `custom_components/bedrock_conversation/translations/`.** That one is config-flow UI strings (JSON) loaded by Home Assistant's integration translation system. This one is service-description metadata (YAML).
- **File format is YAML here, JSON there.** Don't switch formats to "unify" — each is dictated by Home Assistant's translation loader for that surface.
- **Field names here must match the config keys in `../custom_components/bedrock_conversation/const.py`** (`aws_region`, `model_id`, etc.). If you rename a config key, update this file too.
- **Adding a new language**: create `<lang>.yaml` mirroring `en.yaml`'s shape.

### Testing Requirements
- No automated coverage. Verify by loading the integration in a Home Assistant dev instance and inspecting the relevant UI surfaces.

### Common Patterns
- Each top-level entry has `name` (short label) and `description` (longer helper text).

## Dependencies

### Internal
- `../custom_components/bedrock_conversation/const.py` — `CONF_*` keys referenced here.

### External
- Home Assistant's service-description translation loader.

<!-- MANUAL: -->
