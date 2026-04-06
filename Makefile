PYTHON  := .venv/bin/python
RUN_DIR := .run

.PHONY: start stop redis-check trade-ingestion activity-monitor calibration main dashboard monitor volume-spike volatility

# ── Start all required components in the background ────────────────────────────
start: stop redis-check | $(RUN_DIR)
	@nohup env PYTHONUNBUFFERED=1 $(PYTHON) -m market_data.run_trade_ingestion > $(RUN_DIR)/trade_ingestion.log 2>&1 & echo $$! > $(RUN_DIR)/trade_ingestion.pid
	@echo "▶  market_data.run_trade_ingestion  (pid $$(cat $(RUN_DIR)/trade_ingestion.pid))"
	@nohup env PYTHONUNBUFFERED=1 $(PYTHON) -m monitor.calibrate_activity > $(RUN_DIR)/calibration.log 2>&1 & echo $$! > $(RUN_DIR)/calibration.pid
	@echo "▶  monitor.calibrate_activity       (pid $$(cat $(RUN_DIR)/calibration.pid))"
	@nohup env PYTHONUNBUFFERED=1 $(PYTHON) monitor/activity_monitor.py > $(RUN_DIR)/activity_monitor.log 2>&1 & echo $$! > $(RUN_DIR)/activity_monitor.pid
	@echo "▶  monitor/activity_monitor.py      (pid $$(cat $(RUN_DIR)/activity_monitor.pid))"
	@nohup env PYTHONUNBUFFERED=1 $(PYTHON) monitor/app.py > $(RUN_DIR)/monitor.log 2>&1 & echo $$! > $(RUN_DIR)/monitor.pid
	@echo "▶  monitor/app.py                   (pid $$(cat $(RUN_DIR)/monitor.pid))"
	@nohup env PYTHONUNBUFFERED=1 $(PYTHON) -m execute.breakout.main > $(RUN_DIR)/main.log 2>&1 & echo $$! > $(RUN_DIR)/main.pid
	@echo "▶  execute.breakout.main            (pid $$(cat $(RUN_DIR)/main.pid))"
	@nohup env PYTHONUNBUFFERED=1 $(PYTHON) -m execute.trade.dashboard > $(RUN_DIR)/dashboard.log 2>&1 & echo $$! > $(RUN_DIR)/dashboard.pid
	@echo "▶  execute.trade.dashboard          (pid $$(cat $(RUN_DIR)/dashboard.pid))"
	@echo ""
	@echo "Logs → .run/   |   Stop with: make stop"

# ── Stop all background components ────────────────────────────────────────────
stop:
	@for f in $(RUN_DIR)/*.pid; do \
		[ -f "$$f" ] || continue; \
		pid=$$(cat "$$f"); \
		pkill -TERM -P "$$pid" 2>/dev/null; \
		kill "$$pid" 2>/dev/null \
			&& echo "✋ stopped  pid $$pid  ($$f)" \
			|| echo "⚠  already gone  ($$f)"; \
		rm -f "$$f"; \
	done
	@lsof -ti tcp:8080 -ti tcp:8081 2>/dev/null | sort -u | while read pid; do \
		kill "$$pid" 2>/dev/null && echo "✋ killed orphan  pid $$pid"; \
	done; true

# ── Individual foreground targets (dev / debug) ───────────────────────────────
trade-ingestion: redis-check
	$(PYTHON) -m market_data.run_trade_ingestion

activity-monitor: redis-check
	$(PYTHON) monitor/activity_monitor.py

calibration:
	$(PYTHON) -m monitor.calibrate_activity

main: redis-check
	$(PYTHON) -m execute.breakout.main

dashboard:
	$(PYTHON) -m execute.trade.dashboard

monitor: redis-check
	$(PYTHON) monitor/app.py

# ── Optional components ───────────────────────────────────────────────────────
volume-spike: redis-check
	cd monitor && ../.venv/bin/python volume_spike.py

volatility:
	cd monitor && ../.venv/bin/python volatility.py

# ── Prerequisites ─────────────────────────────────────────────────────────────
redis-check:
	@redis-cli ping >/dev/null 2>&1 \
		|| { echo "❌  Redis is not running — start it with: brew services start redis"; exit 1; }
	@echo "✅  Redis OK"

$(RUN_DIR):
	mkdir -p $(RUN_DIR)
