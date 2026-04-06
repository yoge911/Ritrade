import { useEffect, useState } from 'react';
import { formatClockTime } from '../../utils/format';

export function Header() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="header-bar">
      <div>
        <h1 className="header-title">Ritrade Monitor</h1>
      </div>
      <div className="header-timestamp text-sm font-mono">
        Updated {formatClockTime(time)}
      </div>
    </div>
  );
}
