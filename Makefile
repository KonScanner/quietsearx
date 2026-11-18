.PHONY: check lint format test engines compose-validate

# The full check. Run this before every commit.
check: lint test compose-validate

lint:
	ruff check cover/ scripts/
	ruff format --check cover/ scripts/

format:
	ruff format cover/ scripts/
	ruff check --fix cover/ scripts/

test:
	python3 -m unittest discover -s cover -t cover -v
	python3 -m unittest discover -s scripts -t scripts -v

# Report which enabled general engines answer. The container keeps no log, so
# this is the health check for the engines.
engines:
	python3 scripts/check_engines.py

# A placeholder secret lets the check run without a .env file.
compose-validate:
	SEARXNG_SECRET=validate-only docker compose config --quiet
