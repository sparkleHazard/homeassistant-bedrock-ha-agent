# Development Guide

Local development and release workflow for this Home Assistant custom integration.

## Repo Layout

```
.
├── custom_components/bedrock_conversation/  # the integration
│   ├── __init__.py        # setup/teardown, HassServiceTool, BedrockServicesAPI
│   ├── bedrock_client.py  # boto3 wrapper, prompt + tool schema, invoke_model
│   ├── conversation.py    # ConversationEntity, tool-calling loop
│   ├── config_flow.py     # setup + options UI, validate_aws_credentials
│   ├── const.py           # config keys, defaults, allowlists, prompts
│   ├── utils.py           # closest_color, tool-call helpers
│   ├── manifest.json      # version, requirements, dependencies
│   ├── strings.json       # source strings for HA translation pipeline
│   └── translations/      # localized config-flow strings
├── tests/                 # pytest suite (mocks boto3; see tests/AGENTS.md)
├── translations/          # service-description translations (YAML)
├── Makefile               # venv, deps, test, lint, format, release
├── pyproject.toml         # tool configuration (ruff, black, isort, mypy)
├── requirements-dev.txt   # developer tooling
├── requirements-test.txt  # test dependencies
└── AGENTS.md              # architecture reference (per directory)
```

Architecture details live in the `AGENTS.md` files — start at the root one.

## Makefile Targets

| Target | Purpose |
|--------|---------|
| `make venv` | Create `.venv/`. |
| `make deps` | Install test + editable-install dependencies into `.venv/`. |
| `make test` | Full pytest run with coverage into `htmlcov/`. |
| `make test-simple` | Curated fast subset (`test_bedrock_client`, `test_config_flow`, `test_init`, `test_utils`). Used as the release gate. |
| `make lint` | `ruff check .`. |
| `make format` | `black .` + `isort .`. |
| `make typecheck` | `mypy custom_components/`. |
| `make clean` | Remove `.venv/`, caches, coverage artifacts. |
| `make version` | Print the version from `manifest.json`. |
| `make release` | Runs `test-simple`, verifies clean working tree, creates and pushes the `vX.Y.Z` tag, cuts a GitHub release. |
| `make release-no-tests` | Same as `release` but skips tests (use with care). |

There is no `make help` target.

## Typical Workflow

```bash
git clone https://github.com/cronus42/homeassistant-aws-bedrock-conversation-agent
cd homeassistant-aws-bedrock-conversation-agent
make deps           # one-time setup
# hack on code
make format         # keep the formatter happy
make lint
make test-simple    # fast feedback loop
make test           # full suite before PR
```

## Testing Against a Real Home Assistant

Mount or copy the integration into your HA config:

```bash
cp -r custom_components/bedrock_conversation ~/.homeassistant/custom_components/
# restart Home Assistant
```

Enable debug logging to observe the tool-calling loop:

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.bedrock_conversation: debug
```

For a quick smoke test against real Bedrock without Home Assistant, `test_bedrock.py` at the repo root issues a single Bedrock call using `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` / `MODEL_ID` env vars. It is **not** part of the automated suite.

## Release Workflow

Version lives in exactly one place: `custom_components/bedrock_conversation/manifest.json`.

```bash
# 1. Bump version
${EDITOR} custom_components/bedrock_conversation/manifest.json
# 2. Update CHANGELOG.md under a new heading for the new version
${EDITOR} CHANGELOG.md
# 3. Commit
git add custom_components/bedrock_conversation/manifest.json CHANGELOG.md
git commit -m "release: vX.Y.Z"
# 4. Tag and publish
make release
```

`make release` refuses to run with a dirty working tree or an existing tag. Do not pass `--force` to resolve either — commit or delete as appropriate instead.

## Code Style

- Formatter: `black` (default line length).
- Import sorter: `isort`.
- Linter: `ruff` (configured in `pyproject.toml`).
- Type checker: `mypy` on `custom_components/`.
- Follow Home Assistant's [integration development conventions](https://developers.home-assistant.io/docs/creating_integration_manifest).

## Adding a Configuration Option

1. Add `CONF_<NAME>` and `DEFAULT_<NAME>` in `const.py`.
2. Add the field to the options schema in `config_flow.py::BedrockConversationOptionsFlow`.
3. Add a translated label in `strings.json` and every file under `custom_components/bedrock_conversation/translations/`.
4. Read it in the code path that consumes it (`bedrock_client.py` or `conversation.py`).
5. Add a test asserting the default and schema presence (see `tests/test_config_flow.py` / `tests/test_init.py`).

## Adding a Supported Service for Tool-Calling

1. Add the domain to `SERVICE_TOOL_ALLOWED_DOMAINS` (if new) and the specific service to `SERVICE_TOOL_ALLOWED_SERVICES` in `const.py`.
2. Add any new argument keys to `ALLOWED_SERVICE_CALL_ARGUMENTS`.
3. Extend `tests/test_init.py` to confirm the new service passes `HassServiceTool`'s validation.

The allowlists are **security boundaries** — the model can only invoke services on them. Be deliberate.

## Adding a New Model

1. Add the Bedrock model id to `AVAILABLE_MODELS` in `const.py`.
2. If it is not a Claude model, verify `bedrock_client.py::async_generate` handles the body shape (currently Claude uses `temperature` and drops `top_p`; other families receive `top_p`).
3. Update the README's Supported Models section.

## Contributing

Open a PR against `main`. Ensure:

- `make test-simple` passes locally.
- `make lint` is clean.
- New options, services, or models are covered by tests.
- `CHANGELOG.md` has an entry under the next release.
