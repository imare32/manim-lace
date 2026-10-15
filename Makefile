.PHONY: test demo bench lint

test:
	pytest -q

demo:
	python examples/demo_core.py

bench:
	python benchmarks/bench_crossings.py --repeat 3

lint:
	ruff check src tests examples benchmarks
