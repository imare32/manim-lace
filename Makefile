.PHONY: test demo bench lint audit

test:
	pytest -q

demo:
	python examples/demo_core.py

bench:
	python benchmarks/bench_crossings.py --repeat 3

audit:
	python benchmarks/weave_audit.py

lint:
	ruff check src tests examples benchmarks
