import { useState } from 'react';
import { ActivitySnapshotsTable } from './ActivitySnapshotsTable';
import { MinuteSnapshotsTable } from './MinuteSnapshotsTable';

type ActiveTab = 'activity' | 'minute';

export function SnapshotTabs() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('activity');

  return (
    <section className="panel-shell snapshots-shell">
      <div className="panel-header">
        <div className="section-title">Monitoring Snapshots</div>
        <div className="panel-caption">full-width live feed</div>
      </div>

      <div className="snapshot-tabs">
        <button
          className={`tab-button ${activeTab === 'activity' ? 'is-active' : ''}`}
          onClick={() => setActiveTab('activity')}
        >
          20s Snapshots
        </button>
        <button
          className={`tab-button ${activeTab === 'minute' ? 'is-active' : ''}`}
          onClick={() => setActiveTab('minute')}
        >
          1m Signal Snapshots
        </button>
      </div>

      <div className="snapshot-content">
        {activeTab === 'activity' ? <ActivitySnapshotsTable /> : <MinuteSnapshotsTable />}
      </div>
    </section>
  );
}
