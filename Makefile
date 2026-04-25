
.PHONY: test venv deps clean lint format release version typecheck release-no-tests test-no-file-io

venv:
	python3 -m venv .venv

deps: venv
	.venv/bin/pip install -r requirements-test.txt
	.venv/bin/pip install -e .

test: deps
	.venv/bin/pytest tests/ --cov=custom_components.bedrock_ha_agent --cov-report=term-missing --cov-report=html

test-simple: deps
	.venv/bin/pytest tests/test_bedrock_client.py tests/test_config_flow.py tests/test_init.py tests/test_utils.py -v

clean:
	rm -rf .venv
	rm -rf __pycache__
	rm -rf custom_components/bedrock_ha_agent/__pycache__
	rm -rf htmlcov
	rm -f .coverage

lint: test-no-file-io deps
	.venv/bin/ruff check .

test-no-file-io: deps
	.venv/bin/pytest tests/test_no_file_io.py -v

format: deps
	.venv/bin/black .
	.venv/bin/isort .

typecheck: deps
	.venv/bin/mypy custom_components/

version:
	@python3 -c "import json; print(f'Version: {json.load(open(\"custom_components/bedrock_ha_agent/manifest.json\"))["version"]}')"
	@echo "Tag would be: v$(shell python3 -c "import json; print(json.load(open('custom_components/bedrock_ha_agent/manifest.json'))['version'])")"

release: test-simple
	@VERSION=$$(python3 -c "import json; print(json.load(open('custom_components/bedrock_ha_agent/manifest.json'))['version'])") && \
	if git diff-index --quiet HEAD --; then \
		if git tag | grep -q "v$$VERSION"; then \
			echo "Error: Tag v$$VERSION already exists"; \
			exit 1; \
		else \
			echo "Creating tag v$$VERSION" && \
			git tag -a "v$$VERSION" -m "Release v$$VERSION" && \
			git push origin "v$$VERSION" && \
			echo "Creating GitHub release for v$$VERSION" && \
			gh release create "v$$VERSION" --title "Release v$$VERSION" --notes "Automated release of version $$VERSION"; \
		fi \
	else \
		echo "Error: Working tree has uncommitted changes"; \
		exit 1; \
	fi

release-no-tests:
	./release_no_tests.sh
