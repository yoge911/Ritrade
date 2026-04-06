import { useDashboard } from '../../context/DashboardContext';
import { StatusBadge } from '../ui/StatusBadge';
import { formatMetric, signalClass, signalLabel } from '../../utils/format';
import type { TickerSnapshot } from '../../types/models';

export function OverviewSection({ showDetails }: { showDetails: boolean }) {
  const { overview } = useDashboard();

  if (!overview || overview.length === 0) {
    return (
      <div className="glass-panel text-center text-muted">
        Waiting for rolling metrics from activity_monitor…
      </div>
    );
  }

  return (
    <div className="ticker-overview-shell">
      <div className="ticker-card-grid">
        {overview.map((row) => (
          <TickerCard key={row.ticker} row={row} showDetails={showDetails} />
        ))}
      </div>
    </div>
  );
}

function TickerCard({ row, showDetails }: { row: TickerSnapshot; showDetails: boolean }) {
  const { ticker, rolling, setup, minute, latest_trade } = row;

  const sLabel = signalLabel(rolling || {});
  const sClass = signalClass(rolling || {});
  const variant = sClass.replace('signal-', '') as 'cold' | 'warm' | 'hot';

  return (
    <div className="glass-panel ticker-card">
      <div className="ticker-card-header">
        <div className="ticker-card-title-group">
          <h3 className="ticker-card-title">{ticker}</h3>
          <p className="ticker-card-subtitle">Latest rolling state</p>
        </div>
        <StatusBadge label={sLabel} variant={variant} />
      </div>

      <div className="ticker-stat-grid">
        <MetricCard label="Live Price" value={formatMetric(latest_trade?.price, 2)} />
        <MetricCard label="Score" value={formatMetric(rolling?.activity_score, 2)} />
        <MetricCard label="Trades" value={formatMetric(rolling?.trades, 0)} />
        <MetricCard label="Volume" value={formatMetric(rolling?.volume, 3)} />
      </div>

      {showDetails && <div className="ticker-detail-stack">
        <DetailSection title="Rolling">
          <DetailRow label="Time" value={rolling?.timestamp || '—'} />
          <DetailRow label="WAP" value={formatMetric(rolling?.wap, 5)} />
          <DetailRow label="Slope" value={formatMetric(rolling?.slope, 5)} />
        </DetailSection>

        <DetailSection title="Latest Setup">
          <DetailRow label="Start" value={setup?.setup_start_time || '—'} />
          <DetailRow label="End" value={setup?.setup_end_time || '—'} />
          <DetailRow label="Score" value={formatMetric(setup?.activity_score)} />
        </DetailSection>

        <DetailSection title="Minute Summary">
          <DetailRow label="Time" value={minute?.timestamp || '—'} />
          <DetailRow label="Trades" value={formatMetric(minute?.trades, 0)} />
          <DetailRow label="Volume" value={formatMetric(minute?.volume, 3)} />
        </DetailSection>
      </div>}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="ticker-stat-tile">
      <span className="ticker-stat-label">{label}</span>
      <span className="ticker-stat-value">{value}</span>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="ticker-detail-section">
      <div className="ticker-detail-section-title">{title}</div>
      <div className="ticker-detail-grid">{children}</div>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="ticker-detail-row">
      <span className="ticker-detail-label">{label}</span>
      <span className="ticker-detail-value">{value}</span>
    </div>
  );
}
