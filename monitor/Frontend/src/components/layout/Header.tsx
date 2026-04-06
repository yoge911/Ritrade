import { useEffect, useState } from 'react';
import { formatClockTime } from '../../utils/format';

export function Header() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="glass-panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div>
        <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 600 }}>Ritrade Monitor</h1>
        <p className="text-muted" style={{ margin: '0.25rem 0 0 0', fontSize: '0.875rem' }}>
          Rolling trade diagnostics, finalized setup snapshots, and minute rollover summaries
        </p>
      </div>
      <div className="text-muted text-sm font-mono">
        Updated {formatClockTime(time)}
      </div>
    </div>
  );
}
