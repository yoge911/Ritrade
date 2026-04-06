import { useExecutionDashboard } from '../../context/ExecutionDashboardContext';
import type { ExecutionPinnedTicker } from '../../types/models';
import { formatMetric, formatPnl, formatPrice } from '../../utils/format';
import { buildManualOrderCommand, buildTrailingStopCommand } from '../../utils/signals';
import { StatusBadge } from '../ui/StatusBadge';

export function PinnedTickerCard({ card }: { card: ExecutionPinnedTicker }) {
  const { sendCommand, setNotice } = useExecutionDashboard();
  const tickerLabel = card.ticker.toUpperCase();

  async function handleBuySell(side: 'long' | 'short') {
    const { command, notice } = buildManualOrderCommand(card.ticker, side, card.status);
    if (notice) {
      setNotice(notice);
      return;
    }
    if (command) {
      await sendCommand(command, `${side.toUpperCase()} limit submitted for ${tickerLabel}.`);
    }
  }

  async function handleTrail() {
    const { command, notice } = buildTrailingStopCommand(card.ticker, card.status);
    if (notice) {
      setNotice(notice);
      return;
    }
    if (command) {
      await sendCommand(command, `Trailing stop nudged for ${tickerLabel} at ${command.stop_price}.`);
    }
  }

  async function handleClose() {
    await sendCommand(
      { action: 'close_position', ticker: card.ticker.toLowerCase() },
      `Close command sent for ${tickerLabel}.`,
    );
  }

  return (
    <article className="widget-card">
      <div className="widget-header">
        <div className="widget-title-group">
          <h3 className="widget-title">{tickerLabel}</h3>
          <p className="widget-meta">{(card.status.state || 'idle').toUpperCase()} · {(card.status.control_mode || 'manual').toUpperCase()}</p>
        </div>
        <StatusBadge label={card.badge_label} variant={card.score_class} />
      </div>

      <div className="widget-price-row">
        <div>
          <div className="mini-label">Live Price</div>
          <div className="widget-price">{formatPrice(card.status.live_price)}</div>
        </div>
        <div className="widget-price-group align-right">
          <div className="mini-label">P&amp;L</div>
          <div className={`widget-pnl ${card.pnl_class}`}>{formatPnl(card.status.pnl)}</div>
        </div>
      </div>

      <div className="widget-metrics widget-metrics-stack">
        <div className="widget-metric-row">
          <div className="mini-label">Entry</div>
          <div className="mini-value">{formatPrice(card.status.entry_price)}</div>
        </div>
        <div className="widget-metric-row">
          <div className="mini-label">Stop</div>
          <div className="mini-value">{formatPrice(card.status.stop_price)}</div>
        </div>
        <div className="widget-metric-row">
          <div className="mini-label">Score</div>
          <div className={`mini-value signal-text-${card.score_class}`}>{formatMetric(card.activity.activity_score)}</div>
        </div>
      </div>

      <div className="widget-actions">
        <button className="btn btn-buy" onClick={() => handleBuySell('long')}>Buy</button>
        <button className="btn btn-sell" onClick={() => handleBuySell('short')}>Sell</button>
        <button className="btn btn-secondary" onClick={handleTrail}>Trail</button>
        <button className="btn btn-ghost btn-danger" onClick={handleClose}>Close</button>
      </div>

      <div className="widget-footer">
        <span>Zone {card.status.zone || 'Flat'}</span>
        <span>Last {card.last_timestamp}</span>
      </div>
    </article>
  );
}
