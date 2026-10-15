.PHONY: test demo lint

test:
	pytest -q

demo:
	python examples/demo_core.py

lint:
	ruff check src tests examples
