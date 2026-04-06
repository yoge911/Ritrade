import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../api/rest';
import { useWebSocket } from '../hooks/useWebSocket';
import type {
  ExecutionCommandRequest,
  ExecutionDashboardSnapshot,
  NoticeState,
} from '../types/models';

interface ExecutionDashboardContextValue extends ExecutionDashboardSnapshot {
  loading: boolean;
  notice: NoticeState | null;
  clearNotice: () => void;
  setNotice: (notice: NoticeState | null) => void;
  refreshSnapshot: () => Promise<void>;
  sendCommand: (command: ExecutionCommandRequest, successMessage?: string) => Promise<boolean>;
}

const emptySnapshot: ExecutionDashboardSnapshot = {
  tickers: [],
  pinned: [],
  activityRows: [],
  minuteRows: [],
};

const ExecutionDashboardContext = createContext<ExecutionDashboardContextValue | undefined>(undefined);

export function ExecutionDashboardProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<ExecutionDashboardSnapshot>(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<NoticeState | null>(null);

  const applySnapshot = useCallback((next: ExecutionDashboardSnapshot) => {
    setSnapshot(next);
    setLoading(false);
  }, []);

  const refreshSnapshot = useCallback(async () => {
    try {
      const next = await api.getSnapshot();
      applySnapshot(next);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to fetch execute snapshot.';
      setNotice({ tone: 'error', message });
      setLoading(false);
    }
  }, [applySnapshot]);

  useEffect(() => {
    refreshSnapshot();
  }, [refreshSnapshot]);

  useWebSocket((message) => {
    applySnapshot(message.payload);
  });

  const sendCommand = useCallback(async (command: ExecutionCommandRequest, successMessage?: string) => {
    try {
      await api.sendCommand(command);
      if (successMessage) {
        setNotice({ tone: 'success', message: successMessage });
      }
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to send command.';
      setNotice({ tone: 'error', message });
      return false;
    }
  }, []);

  const value = useMemo(() => ({
    ...snapshot,
    loading,
    notice,
    clearNotice: () => setNotice(null),
    setNotice,
    refreshSnapshot,
    sendCommand,
  }), [snapshot, loading, notice, refreshSnapshot, sendCommand]);

  return (
    <ExecutionDashboardContext.Provider value={value}>
      {children}
    </ExecutionDashboardContext.Provider>
  );
}

export function useExecutionDashboard() {
  const context = useContext(ExecutionDashboardContext);
  if (!context) {
    throw new Error('useExecutionDashboard must be used within ExecutionDashboardProvider');
  }
  return context;
}
