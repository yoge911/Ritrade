PYTHON    := .venv/bin/python
STREAMLIT := .venv/bin/streamlit
RUN_DIR   := .run

.PHONY: start stop redis-check candle-roll main dashboard monitor volume-spike volatility

# ── Start all required components in the background ────────────────────────────
start: redis-check | $(RUN_DIR)
	@nohup env PYTHONUNBUFFERED=1 $(PYTHON) monitor/candle_roll.py > $(RUN_DIR)/candle_roll.log 2>&1 & echo $$! > $(RUN_DIR)/candle_roll.pid
	@echo "▶  monitor/candle_roll.py      (pid $$(cat $(RUN_DIR)/candle_roll.pid))"
	@nohup env PYTHONUNBUFFERED=1 $(PYTHON) monitor/app.py > $(RUN_DIR)/monitor.log 2>&1 & echo $$! > $(RUN_DIR)/monitor.pid
	@echo "▶  monitor/app.py              (pid $$(cat $(RUN_DIR)/monitor.pid))"
	@nohup env PYTHONUNBUFFERED=1 $(PYTHON) -m execute.breakout.main > $(RUN_DIR)/main.log 2>&1 & echo $$! > $(RUN_DIR)/main.pid
	@echo "▶  execute.breakout.main        (pid $$(cat $(RUN_DIR)/main.pid))"
	@nohup env PYTHONUNBUFFERED=1 $(PYTHON) -m execute.trade.dashboard > $(RUN_DIR)/dashboard.log 2>&1 & echo $$! > $(RUN_DIR)/dashboard.pid
	@echo "▶  execute.trade.dashboard      (pid $$(cat $(RUN_DIR)/dashboard.pid))"
	@echo ""
	@echo "Logs → .run/   |   Stop with: make stop"

# ── Stop all background components ────────────────────────────────────────────
stop:
	@for f in $(RUN_DIR)/*.pid; do \
		[ -f "$$f" ] || continue; \
		pid=$$(cat "$$f"); \
		kill "$$pid" 2>/dev/null \
			&& echo "✋ stopped  pid $$pid  ($$f)" \
			|| echo "⚠  already gone  ($$f)"; \
		rm -f "$$f"; \
	done

# ── Individual foreground targets (dev / debug) ───────────────────────────────
candle-roll: redis-check
	$(PYTHON) monitor/candle_roll.py

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
