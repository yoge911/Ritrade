import { useExecutionDashboard } from '../../context/ExecutionDashboardContext';
import { EmptyState } from '../ui/EmptyState';
import { PinnedTickerCard } from './PinnedTickerCard';

export function PinnedTickersPanel() {
  const { pinned } = useExecutionDashboard();

  return (
    <section className="panel-shell">
      <div className="section-title">Pinned Tickers</div>
      {pinned.length === 0 ? (
        <EmptyState message="Pin a ticker from Signals to start live execution tracking." />
      ) : (
        <div className="widget-row">
          {pinned.map((card) => (
            <PinnedTickerCard key={card.ticker} card={card} />
          ))}
        </div>
      )}
    </section>
  );
}
