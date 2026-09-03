.PHONY: run run-shell run-helper run-agents run-all test check init-db package

PYTHON ?= python3

run:  ## Start the AgentOS daemon
	$(PYTHON) -m cmd.agentosd

run-shell:  ## Launch the desktop shell (requires GTK4 + libadwaita)
	$(PYTHON) -m agentos.shell.main

run-helper:  ## Start the privileged helper (requires root)
	sudo $(PYTHON) -m agentos.helper.main

run-agents:  ## Start all bundled agents in the background
	$(PYTHON) agents/assistant_agent.py &
	$(PYTHON) agents/file_agent.py &
	$(PYTHON) agents/shell_agent.py &
	$(PYTHON) agents/system_agent.py &

run-all: run run-agents  ## Start daemon + all agents

test:
	$(PYTHON) -m unittest discover -s tests -v

check:
	$(PYTHON) -m compileall -q agentos cmd agents tests
	$(PYTHON) -m unittest discover -s tests -v

init-db:
	$(PYTHON) scripts/init_db.py

package:
	scripts/build_deb.sh
