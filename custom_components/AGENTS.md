<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-25 | Updated: 2026-04-26 -->

# custom_components

## Purpose
Home Assistant custom-component root. Home Assistant auto-discovers integrations under this directory when the repo is installed into `config/custom_components/` (or symlinked there for local development). Each subdirectory is a separate integration domain; this repo ships exactly one.

## Key Files
None at this level. The directory is a namespace container — Home Assistant walks its subdirectories.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `bedrock_ha_agent/` | The AWS Bedrock conversation + config-editing + diagnostics integration (see `bedrock_ha_agent/AGENTS.md`). Domain: `bedrock_ha_agent`. |

## For AI Agents

### Working In This Directory
- Do not add files directly here. Home Assistant treats each subdirectory's `manifest.json` as the integration boundary; stray files at this level can confuse the loader.
- If adding a new integration in the future, create a new subdirectory with its own `manifest.json`, `__init__.py`, and `const.py` — don't share code by importing across integrations.

### Testing Requirements
- Coverage is configured against `custom_components.bedrock_ha_agent` (see `Makefile`). New integrations would need their own coverage path.

### Common Patterns
- Each integration sets its `DOMAIN` constant in `const.py` to match its directory name.

## Dependencies

### Internal
None — this directory is a pure container.

### External
None directly. Children declare their own `requirements` in `manifest.json`.

<!-- MANUAL: -->
