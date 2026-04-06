import { useState } from 'react';
import { DashboardProvider } from './context/DashboardContext';
import { DashboardLayout } from './components/layout/DashboardLayout';
import { Header } from './components/layout/Header';
import { CalibrationPanel } from './components/calibration/CalibrationPanel';
import { OverviewSection } from './components/overview/OverviewSection';
import { FeedsTabs } from './components/feeds/FeedsTabs';
import './index.css';

function App() {
  const [showDetails, setShowDetails] = useState(false);

  return (
    <DashboardProvider>
      <DashboardLayout>
        <Header />
        <div className="workspace-shell">
          <div className="workspace-toggle-anchor">
            <button
              className="ticker-grid-toggle workspace-floating-toggle"
              onClick={() => setShowDetails((value) => !value)}
              aria-label={showDetails ? 'Hide ticker details' : 'Show ticker details'}
              title={showDetails ? 'Hide ticker details' : 'Show ticker details'}
            >
              <span className={`ticker-grid-toggle-arrow ${showDetails ? 'is-open' : ''}`}>⌄</span>
            </button>
          </div>
          <div className="workspace-main">
            <OverviewSection showDetails={showDetails} />
            <FeedsTabs />
          </div>
          <div className="workspace-side">
            <CalibrationPanel />
          </div>
        </div>
      </DashboardLayout>
    </DashboardProvider>
  );
}

export default App;
