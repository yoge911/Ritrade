import { useState, useMemo } from 'react';
import { useDashboard } from '../../context/DashboardContext';
import { DataTable, Column } from '../ui/DataTable';
import { formatMetric, signalLabel, formatDurationMs } from '../../utils/format';
import type { RollingMetric, SetupSnapshot, MinuteSnapshot } from '../../types/models';

export function FeedsTabs() {
  const [activeTab, setActiveTab] = useState<'rolling' | 'setup' | 'minute'>('rolling');
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="glass-panel monitor-feeds-panel" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.125rem', fontWeight: 600 }}>Monitor Feeds</h2>
        </div>
        <button className="btn" onClick={() => setIsOpen((value) => !value)}>
          {isOpen ? 'Hide Feeds' : 'Show Feeds'}
        </button>
      </div>

      {isOpen && (
        <>
          <div style={{ display: 'flex', gap: '1rem', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '0.5rem' }}>
            <TabButton active={activeTab === 'rolling'} onClick={() => setActiveTab('rolling')}>Rolling 10s Diagnostics</TabButton>
            <TabButton active={activeTab === 'setup'} onClick={() => setActiveTab('setup')}>Finalized Setup Snapshots</TabButton>
            <TabButton active={activeTab === 'minute'} onClick={() => setActiveTab('minute')}>Minute Rollover Summary</TabButton>
          </div>
          
          <div>
            {activeTab === 'rolling' && <RollingTable />}
            {activeTab === 'setup' && <SetupTable />}
            {activeTab === 'minute' && <MinuteTable />}
          </div>
        </>
      )}
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button 
      onClick={onClick}
      style={{
        background: 'none',
        border: 'none',
        color: active ? 'var(--accent-primary)' : 'var(--text-muted)',
        fontWeight: active ? 600 : 400,
        cursor: 'pointer',
        padding: '0.5rem',
        borderBottom: active ? '2px solid var(--accent-primary)' : '2px solid transparent',
        marginBottom: '-0.6rem'
      }}
    >
      {children}
    </button>
  );
}

function RollingTable() {
  const { rolling } = useDashboard();
  
  const columns: Column<RollingMetric>[] = useMemo(() => [
    { name: 'ticker', label: 'Ticker', format: (r) => r.ticker?.toUpperCase() || '—' },
    { name: 'time', label: 'Time', format: (r) => r.timestamp || '—' },
    { name: 'signal', label: 'Signal', format: (r) => signalLabel(r) },
    { name: 'score', label: 'Score', align: 'right', format: (r) => formatMetric(r.activity_score) },
    { name: 'trades', label: 'Trades', align: 'right', format: (r) => formatMetric(r.trades, 0) },
    { name: 'volume', label: 'Volume', align: 'right', format: (r) => formatMetric(r.volume, 3) },
    { name: 'wap', label: 'WAP', align: 'right', format: (r) => formatMetric(r.wap, 5) },
    { name: 'std_dev', label: 'Std Dev', align: 'right', format: (r) => formatMetric(r.std_dev, 5) },
    { name: 'slope', label: 'Slope', align: 'right', format: (r) => formatMetric(r.slope, 5) },
  ], []);

  const data = useMemo(() => [...rolling].reverse(), [rolling]);
  
  return (
    <DataTable
      data={data}
      columns={columns}
      rowKey={(r, index) => `${r.ticker || 'unknown'}-${r.timestamp || 'no-time'}-${index}`}
    />
  );
}

function SetupTable() {
  const { setups } = useDashboard();
  
  const columns: Column<SetupSnapshot>[] = useMemo(() => [
    { name: 'ticker', label: 'Ticker', format: (r) => r.ticker?.toUpperCase() || '—' },
    { name: 'setup_start', label: 'Start', format: (r) => r.setup_start_time || '—' },
    { name: 'setup_end', label: 'End', format: (r) => r.setup_end_time || r.timestamp || '—' },
    { name: 'duration', label: 'Window', align: 'right', format: (r) => formatDurationMs(r.qualification_duration_ms) },
    { name: 'signal', label: 'Signal', format: (r) => signalLabel(r) },
    { name: 'score', label: 'Score', align: 'right', format: (r) => formatMetric(r.activity_score) },
    { name: 'trades', label: 'Trades', align: 'right', format: (r) => formatMetric(r.trades, 0) },
    { name: 'volume', label: 'Volume', align: 'right', format: (r) => formatMetric(r.volume, 3) },
    { name: 'trigger', label: 'Trigger', format: (r) => r.trigger_reason || '—' },
  ], []);

  const data = useMemo(() => [...setups].reverse(), [setups]);
  
  return (
    <DataTable
      data={data}
      columns={columns}
      rowKey={(r, index) => `${r.ticker || 'unknown'}-${r.setup_end_time || r.timestamp || 'no-time'}-${index}`}
    />
  );
}

function MinuteTable() {
  const { minutes } = useDashboard();
  
  const columns: Column<MinuteSnapshot>[] = useMemo(() => [
    { name: 'ticker', label: 'Ticker', format: (r) => r.ticker?.toUpperCase() || '—' },
    { name: 'minute', label: 'Minute', format: (r) => r.timestamp || '—' },
    { name: 'trades', label: 'Trades', align: 'right', format: (r) => formatMetric(r.trades, 0) },
    { name: 'volume', label: 'Volume', align: 'right', format: (r) => formatMetric(r.volume, 3) },
    { name: 'avg_price', label: 'Avg Price', align: 'right', format: (r) => formatMetric(r.avg_price, 5) },
  ], []);
  
  const data = useMemo(() => [...minutes].reverse(), [minutes]);
  
  return (
    <DataTable
      data={data}
      columns={columns}
      rowKey={(r, index) => `${r.ticker || 'unknown'}-${r.timestamp || 'no-time'}-${index}`}
    />
  );
}
