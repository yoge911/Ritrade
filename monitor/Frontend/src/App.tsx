import { DashboardProvider } from './context/DashboardContext';
import { DashboardLayout } from './components/layout/DashboardLayout';
import { Header } from './components/layout/Header';
import { CalibrationPanel } from './components/calibration/CalibrationPanel';
import { OverviewSection } from './components/overview/OverviewSection';
import { FeedsTabs } from './components/feeds/FeedsTabs';
import './index.css';

function App() {
  return (
    <DashboardProvider>
      <DashboardLayout>
        <Header />
        <CalibrationPanel />
        <OverviewSection />
        <FeedsTabs />
      </DashboardLayout>
    </DashboardProvider>
  );
}

export default App;
