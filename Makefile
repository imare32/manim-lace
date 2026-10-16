.PHONY: test test-fast demo bench lint audit

test:
	pytest -q

test-fast:
	pytest -q --skip-heavy

demo:
	python examples/demo_core.py

bench:
	python benchmarks/bench_crossings.py --repeat 3

audit:
	python benchmarks/weave_audit.py

lint:
	ruff check src tests examples benchmarks
