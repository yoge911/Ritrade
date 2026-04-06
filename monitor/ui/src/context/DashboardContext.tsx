import { createContext, useContext, useEffect, useState, ReactNode, useCallback } from 'react';
import { api } from '../api/rest';
import { useWebSocket } from '../hooks/useWebSocket';
import type {
  TickerSnapshot,
  RollingMetric,
  SetupSnapshot,
  MinuteSnapshot,
  ActiveCalibrationState,
  MonitorSnapshotPayload,
} from '../types/models';

interface DashboardState {
  overview: TickerSnapshot[];
  rolling: RollingMetric[];
  setups: SetupSnapshot[];
  minutes: MinuteSnapshot[];
  calibrationState: ActiveCalibrationState | null;
  refreshCalibrationState: () => Promise<void>;
  updateCalibrationState: (state: ActiveCalibrationState | null) => void;
}

const DashboardContext = createContext<DashboardState | undefined>(undefined);

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [overview, setOverview] = useState<TickerSnapshot[]>([]);
  const [rolling, setRolling] = useState<RollingMetric[]>([]);
  const [setups, setSetups] = useState<SetupSnapshot[]>([]);
  const [minutes, setMinutes] = useState<MinuteSnapshot[]>([]);
  const [calibrationState, setCalibrationState] = useState<ActiveCalibrationState | null>(null);

  const applyMonitorSnapshot = useCallback((payload: MonitorSnapshotPayload) => {
    setOverview(payload.overview);
    setRolling(payload.rolling);
    setSetups(payload.setups);
    setMinutes(payload.minutes);
    setCalibrationState(payload.calibrationState);
  }, []);

  const refreshCalibrationState = useCallback(async () => {
    try {
      const state = await api.getCalibrationState();
      setCalibrationState(state);
    } catch (e) {
      console.error('Failed to fetch calibration state', e);
    }
  }, []);

  useEffect(() => {
    refreshCalibrationState();
  }, [refreshCalibrationState]);

  useWebSocket((message) => {
    applyMonitorSnapshot(message.payload);
  });

  return (
    <DashboardContext.Provider
      value={{
        overview,
        rolling,
        setups,
        minutes,
        calibrationState,
        refreshCalibrationState,
        updateCalibrationState: setCalibrationState,
      }}
    >
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard() {
  const context = useContext(DashboardContext);
  if (!context) throw new Error('useDashboard must be used within DashboardProvider');
  return context;
}
