
.DEFAULT_GOAL := test

env:
	virtualenv -p python3 --always-copy env

install:
	env/bin/pip install .

dev-install:
	env/bin/pip install -r requirements.txt
	env/bin/pip install -e .

run:
	2vyper $(file)

test:
	env/bin/pytest tests/run_tests.py

test-carbon:
	env/bin/pytest --verifier carbon tests/run_tests.py

clean:
	find ./src -type d -name __pycache__ -exec rm -r {} \+

clean-egg:
	find ./src/ -type d -name *.egg-info -exec rm -r {} \+

clean-env: clean clean-egg
	rm -r env

.PHONY: env install dev-install run test test-carbon clean clean-egg clean-env
