.PHONY: run stop

PORT ?= 8080

help:
	@echo "KindleVibe-Python — usage dashboard for Kindle"
	@echo ""
	@echo "  make run    Start server (configure port in config.json)"
	@echo "  make stop   Stop server on port $(PORT)"
	@echo ""

run:
	@echo "Starting KindleVibe-Python..."
	python3 app.py

stop:
	@if lsof -ti tcp:$(PORT) >/dev/null 2>&1; then \
		kill $$(lsof -ti tcp:$(PORT)); \
		echo "Stopped."; \
	else \
		echo "Not running."; \
	fi
