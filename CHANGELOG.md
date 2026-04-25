# Changelog

All notable changes to this project are documented here.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions. Detailed per-release notes live on GitHub Releases; this file captures the higher-level history.

## 1.0.37

### Fixed
- Options flow crashed with `AttributeError: property 'config_entry' of 'BedrockConversationOptionsFlow' object has no setter` in recent Home Assistant versions. The `OptionsFlow` base class now exposes `config_entry` as a read-only property and subclasses must not assign to it in `__init__`. Removed the override; the config entry is still available via `self.config_entry`.
- Model-id selector now tolerates a stored value that is no longer in `AVAILABLE_MODELS` (e.g. after removing legacy Claude 3.5 ids). The current value is appended to the dropdown options and `custom_value=True` is enabled so opening the options flow no longer fails for upgraded installs.

## Unreleased

### Changed
- Documentation overhaul: single primary README at the repo root; removed add-on-style installation content that did not apply to this custom integration.
- Logging: stripped emoji/debug banners and demoted lifecycle events from ERROR to INFO/DEBUG.

### Removed
- Legacy Goose-era memory files (`.goose/`, `.goosehints`).
- `top_k` configuration option — it was being silently discarded on the Bedrock request path, so the UI knob was dead.
- `INSTALL.md`, `WARP.md`, `TESTING_GUIDE.md`, and `tests/README.md` — obsolete or superseded by the new README/AGENTS.md layout.

### Added
- `brightness_pct` and `tilt_position` to the tool-calling service-argument allowlist.
- Hierarchical `AGENTS.md` files describing each part of the repo.

### Fixed
- Config-flow error keys (`unknown_error` → `unknown`) now match the entries in `strings.json` / `translations/en.json`.
- Double-blank-line / unused-import leftovers from the cleanup pass.

## 1.0.36 and earlier

Pre-1.0.36 history is tracked in git. Notable themes up to this version:

- Initial HACS custom integration delivering a Home Assistant conversation agent backed by AWS Bedrock.
- Claude 4.x model support (`claude-sonnet-4-5`, `claude-haiku-4-5`) with the haiku variant as default.
- Native Bedrock tool-calling wired through `homeassistant.helpers.llm.Tool` so Claude can invoke Home Assistant services directly (`HassCallService` tool).
- System-prompt generation from exposed entities and areas, with Jinja templating and per-turn refresh.
- Config flow with AWS credential validation via `bedrock:ListFoundationModels`, and an options flow for model parameters and memory behavior.
- `boto3` calls pushed onto the executor so the event loop is never blocked.
- Allowlist-based safety boundaries on the service-calling tool (`SERVICE_TOOL_ALLOWED_DOMAINS`, `SERVICE_TOOL_ALLOWED_SERVICES`, `ALLOWED_SERVICE_CALL_ARGUMENTS`).

For the exact diff between any two versions, use git tags:

```bash
git log --oneline v1.0.35..v1.0.36
```

or view the release on GitHub at
`https://github.com/cronus42/homeassistant-aws-bedrock-conversation-agent/releases`.
