import { useDashboard } from '../../context/DashboardContext';
import { StatusBadge } from '../ui/StatusBadge';
import { formatMetric, signalClass, signalLabel } from '../../utils/format';
import type { TickerSnapshot } from '../../types/models';

export function OverviewSection() {
  const { overview } = useDashboard();

  if (!overview || overview.length === 0) {
    return (
      <div className="glass-panel text-center text-muted">
        Waiting for rolling metrics from activity_monitor…
      </div>
    );
  }

  return (
    <div>
      <h2 style={{ fontSize: '1.125rem', marginBottom: '1rem', fontWeight: 600 }}>Per-Ticker Snapshot</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '1rem' }}>
        {overview.map((row) => (
          <TickerCard key={row.ticker} row={row} />
        ))}
      </div>
    </div>
  );
}

function TickerCard({ row }: { row: TickerSnapshot }) {
  const { ticker, rolling, setup, minute, latest_trade } = row;
  
  const sLabel = signalLabel(rolling || {});
  const sClass = signalClass(rolling || {});
  const variant = sClass.replace('signal-', '') as 'cold' | 'warm' | 'hot';

  return (
    <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 600 }}>{ticker}</h3>
          <p className="text-muted text-xs" style={{ margin: 0 }}>Latest rolling state</p>
        </div>
        <StatusBadge label={sLabel} variant={variant} />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
        <MetricCard label="Live Price" value={formatMetric(latest_trade?.price, 2)} />
        <MetricCard label="Score" value={formatMetric(rolling?.activity_score, 2)} />
        <MetricCard label="Trades" value={formatMetric(rolling?.trades, 0)} />
        <MetricCard label="Volume" value={formatMetric(rolling?.volume, 3)} />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', fontSize: '0.75rem' }} className="text-muted">
        <div>
          <strong className="text-main">Rolling:</strong> {rolling?.timestamp || '—'} · WAP {formatMetric(rolling?.wap, 5)} · Slope {formatMetric(rolling?.slope, 5)}
        </div>
        <div>
          <strong className="text-main">Latest setup:</strong> {setup?.setup_start_time || '—'} &rarr; {setup?.setup_end_time || '—'} · Score {formatMetric(setup?.activity_score)}
        </div>
        <div>
          <strong className="text-main">Minute summary:</strong> {minute?.timestamp || '—'} · Trades {formatMetric(minute?.trades, 0)} · Volume {formatMetric(minute?.volume, 3)}
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
      <span className="text-muted" style={{ fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
      <span className="text-main font-mono" style={{ fontSize: '1.125rem', fontWeight: 500 }}>{value}</span>
    </div>
  );
}
