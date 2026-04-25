<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-25 | Updated: 2026-04-25 -->

# translations

## Purpose
Localized strings for the integration's config flow and options flow UI. Home Assistant loads these files based on the user's configured language. The source of truth for keys is `../strings.json`; translation files mirror its structure per language.

## Key Files

| File | Description |
|------|-------------|
| `en.json` | English translations for the `config` setup flow (step, error, abort messages) and the `options` flow. Mirrors the shape of `../strings.json`. |

## For AI Agents

### Working In This Directory
- **Keep keys in sync with `../strings.json`.** If you add a new config field, error, or options step, add a matching key to `strings.json` **and** to every translation file here. Home Assistant will log missing-key warnings otherwise.
- **Do not translate keys, only values.** The JSON key structure must match `strings.json` byte-for-byte.
- **Adding a new language** means creating `<lang>.json` here with the same structure as `en.json`. The language code must match Home Assistant's locale identifiers (e.g., `de`, `fr`, `es`, `nl`).
- **Two unrelated translation directories exist in this repo**: this one (`custom_components/bedrock_ha_agent/translations/`) is the HA-loaded UI translations. The sibling `translations/` at the repo root is a service-description YAML — do not conflate them.

### Testing Requirements
- No automated translation tests. Manual verification: install the integration, switch HA's UI to the target language, and confirm the config/options flow labels render correctly.

### Common Patterns
- Descriptions (`description` field) can be longer and include user-facing guidance (e.g., "Please check your access key and secret key.") — these appear as helper text under form fields.
- Titles (`title`) appear in the step header; keep them short.

## Dependencies

### Internal
- `../strings.json` — key schema source of truth.
- `../config_flow.py` — emits the error codes (`invalid_credentials`, `access_denied`, etc.) that the `config.error` keys here translate.

### External
- Home Assistant's translation loader (no package import — file conventions only).

<!-- MANUAL: -->
