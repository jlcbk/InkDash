.PHONY: run stop test help

# Default port
PORT ?= 8080

help:
	@echo "KindleVibe-Python - Codex usage dashboard for Kindle"
	@echo ""
	@echo "Usage:"
	@echo "  make run          Start the server on port $(PORT)"
	@echo "  make run PORT=9090 Start the server on port 9090"
	@echo "  make stop         Stop the server"
	@echo "  make test         Test Codex CLI connection"
	@echo ""

run:
	@echo "Starting KindleVibe-Python on port $(PORT)..."
	python3 app.py --port $(PORT)

stop:
	@echo "Stopping KindleVibe-Python..."
	@if lsof -ti tcp:$(PORT) >/dev/null 2>&1; then \
		kill $$(lsof -ti tcp:$(PORT)); \
		echo "Stopped."; \
	else \
		echo "Not running."; \
	fi

test:
	@echo "Testing Codex CLI connection..."
	@codex /status 2>&1 || echo "Error: codex /status failed"
