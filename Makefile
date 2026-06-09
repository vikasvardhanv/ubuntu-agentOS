.PHONY: run test check init-db

PYTHON ?= python3

run:
	$(PYTHON) -m cmd.agentosd

test:
	$(PYTHON) -m unittest discover -s tests -v

check:
	$(PYTHON) -m compileall -q agentos cmd tests
	$(PYTHON) -m unittest discover -s tests -v

init-db:
	$(PYTHON) scripts/init_db.py
