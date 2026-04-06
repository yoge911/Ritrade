import { useMemo } from 'react';
import { useExecutionDashboard } from '../../context/ExecutionDashboardContext';
import type { Column } from '../ui/DataTable';
import { DataTable } from '../ui/DataTable';
import type { ExecutionSignalRow } from '../../types/models';
import { formatMetric, fallbackText } from '../../utils/format';
import { isPositiveSignal } from '../../utils/signals';

export function ActivitySnapshotsTable() {
  const { activityRows, sendCommand } = useExecutionDashboard();

  const columns = useMemo<Column<ExecutionSignalRow>[]>(() => [
    { name: 'ticker', label: 'Ticker', format: (row) => <span className="strong-cell">{row.ticker}</span> },
    { name: 'timestamp', label: 'Time', format: (row) => fallbackText(row.timestamp) },
    { name: 'score', label: 'Score', align: 'right', format: (row) => formatMetric(row.activity_score) },
    { name: 'qualified', label: 'Qualified', format: (row) => row.qualified },
    { name: 'trades', label: 'Trades', align: 'right', format: (row) => formatMetric(row.trades, 0) },
    { name: 'volume', label: 'Volume', align: 'right', format: (row) => formatMetric(row.volume) },
    { name: 'wap', label: 'WAP', align: 'right', format: (row) => formatMetric(row.wap) },
    { name: 'slope', label: 'Slope', align: 'right', format: (row) => formatMetric(row.slope) },
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
      data={activityRows}
      columns={columns}
      rowKey={(row, index) => `${row.ticker}-${row.timestamp || 'no-time'}-${index}`}
      rowClassName={(row) => isPositiveSignal(row) ? 'positive-row' : undefined}
    />
  );
}
