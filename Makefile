.PHONY: install test demo serve desk

install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/pytest

demo:
	.venv/bin/python -m merchantops.demo

serve:
	.venv/bin/merchantops --transport streamable-http

desk:
	.venv/bin/merchantops-desk
