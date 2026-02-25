.PHONY: test lint check

test:
	PYTHONPATH=. pytest -q

lint:
	python -m compileall app tests
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check app tests; \
	else \
		echo "ruff not installed; skipped"; \
	fi

check: lint test
