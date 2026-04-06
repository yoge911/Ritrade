import { useMemo } from 'react';
import { useExecutionDashboard } from '../../context/ExecutionDashboardContext';
import type { ExecutionMinuteRow } from '../../types/models';
import type { Column } from '../ui/DataTable';
import { DataTable } from '../ui/DataTable';
import { fallbackText, formatMetric } from '../../utils/format';
import { isPositiveSignal } from '../../utils/signals';

export function MinuteSnapshotsTable() {
  const { minuteRows, sendCommand } = useExecutionDashboard();

  const columns = useMemo<Column<ExecutionMinuteRow>[]>(() => [
    { name: 'ticker', label: 'Ticker', format: (row) => <span className="strong-cell">{row.ticker}</span> },
    { name: 'minute_timestamp', label: '1m Time', format: (row) => fallbackText(row.minute_timestamp) },
    { name: 'minute_trades', label: 'Trades', align: 'right', format: (row) => formatMetric(row.minute_trades, 0) },
    { name: 'minute_volume', label: 'Volume', align: 'right', format: (row) => formatMetric(row.minute_volume) },
    { name: 'minute_avg_price', label: 'Avg Price', align: 'right', format: (row) => formatMetric(row.minute_avg_price) },
    { name: 'activity_score', label: '20s Score', align: 'right', format: (row) => formatMetric(row.activity_score) },
    { name: 'signal', label: 'Signal', format: (row) => isPositiveSignal(row) ? 'Positive' : 'Watch' },
    {
      name: 'action',
      label: 'Action',
      format: (row) => (
        <button
          className={`btn table-action-btn ${row.is_pinned ? 'btn-ghost' : 'btn-secondary'}`}
          onClick={() => sendCommand({
            action: row.is_pinned ? 'unpin_ticker' : 'pin_ticker',
            ticker: row.ticker.toLowerCase(),
          })}
        >
          {row.is_pinned ? 'Unpin' : 'Pin'}
        </button>
      ),
    },
  ], [sendCommand]);

  return (
    <DataTable
      data={minuteRows}
      columns={columns}
      rowKey={(row, index) => `${row.ticker}-${row.minute_timestamp || 'no-time'}-${index}`}
      rowClassName={(row) => isPositiveSignal(row) ? 'positive-row' : undefined}
    />
  );
}
