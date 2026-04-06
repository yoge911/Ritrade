import { Header } from './components/layout/Header';
import { PinnedTickersPanel } from './components/pinned/PinnedTickersPanel';
import { SnapshotTabs } from './components/snapshots/SnapshotTabs';
import { ExecutionDashboardProvider, useExecutionDashboard } from './context/ExecutionDashboardContext';

function ExecuteWorkspace() {
  const { notice, clearNotice, loading } = useExecutionDashboard();

  return (
    <div className="app-shell">
      <Header />
      {notice && (
        <div className={`notice-banner notice-${notice.tone}`}>
          <span>{notice.message}</span>
          <button className="notice-dismiss" onClick={clearNotice} aria-label="Dismiss notice">×</button>
        </div>
      )}
      <main className="content-shell">
        {loading ? (
          <div className="loading-panel">Loading execution snapshot…</div>
        ) : (
          <>
            <PinnedTickersPanel />
            <SnapshotTabs />
          </>
        )}
      </main>
    </div>
  );
}

function App() {
  return (
    <ExecutionDashboardProvider>
      <ExecuteWorkspace />
    </ExecutionDashboardProvider>
  );
}

export default App;
