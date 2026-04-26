<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-25 | Updated: 2026-04-26 -->

# translations

## Purpose
Localized strings for the integration's config flow and options flow UI, plus service descriptions surfaced in HA's Developer Tools. Home Assistant loads these files based on the user's configured language. The source of truth for keys is `../strings.json`; translation files mirror its structure per language.

## Key Files

| File | Description |
|------|-------------|
| `en.json` | English translations for the `config` setup flow (step, error, abort messages), the `options` flow (including `CONF_ENABLE_CONFIG_EDITING` and the Haiku advisory), and service descriptions (`undo_last`). Mirrors the shape of `../strings.json`. |

## For AI Agents

### Working In This Directory
- **Keep keys in sync with `../strings.json`.** If you add a new config field, error, or options step, add a matching key to `strings.json` AND to every translation file here. HA will log missing-key warnings otherwise.
- **Do not translate keys, only values.** The JSON key structure must match `strings.json` byte-for-byte.
- **Adding a new language** means creating `<lang>.json` here with the same structure as `en.json`. The language code must match HA's locale identifiers (e.g. `de`, `fr`, `es`, `nl`).
- **No HTML/XML in values.** The v1.1.1 `UNCLOSED_TAG` bug came from `<current_date>`/`<devices>` prompt placeholders appearing in translated strings. Use `{{token}}` syntax in user-visible strings, or HTML-entity-escape if you must reference raw `<...>` tokens.
- **Two unrelated translation directories exist in this repo.** This one (`custom_components/bedrock_ha_agent/translations/`) is the HA-loaded UI translations. The sibling `translations/` at the repo root is service-description YAML — do not conflate them.

### Testing Requirements
- `tests/test_translations.py` asserts that every key in `strings.json` has a corresponding entry in `en.json` (and flags orphans in the other direction). Manual verification for non-English: switch HA's UI to the target language and confirm the config/options flow labels render correctly.

### Common Patterns
- Descriptions (`description` field) can be longer and include user-facing guidance ("Please check your access key and secret key.") — these appear as helper text under form fields.
- Titles (`title`) appear in the step header; keep them short.
- Options-flow `data_description` is where the Haiku advisory text lives.

## Dependencies

### Internal
- `../strings.json` — key schema source of truth.
- `../config_flow.py` — emits the error codes (`invalid_credentials`, `access_denied`, etc.) that the `config.error` keys here translate.
- `../const.py` — the option keys referenced in `options.step.init.data` entries.

### External
- Home Assistant's translation loader (no package import — file conventions only).

<!-- MANUAL: -->
