PY ?= .venv/bin/python

.PHONY: gate lint test results site check-benchmark

gate: lint test

lint:
	$(PY) -m ruff check hca tests scripts

test:
	$(PY) -m pytest -q

check-benchmark:
	$(PY) scripts/check_benchmark.py 300

results:
	$(PY) scripts/make_results.py
	$(PY) scripts/make_slides.py

site:
	$(PY) scripts/publish_hf.py
