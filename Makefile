.PHONY: check lint format test compose-validate

# The full check. Run this before every commit.
check: lint test compose-validate

lint:
	ruff check cover/
	ruff format --check cover/

format:
	ruff format cover/
	ruff check --fix cover/

test:
	python3 -m unittest discover -s cover -t cover -v

# A placeholder secret lets the check run without a .env file.
compose-validate:
	SEARXNG_SECRET=validate-only docker compose config --quiet
