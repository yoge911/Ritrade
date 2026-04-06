import type {
  ActiveCalibrationState,
  ArchivePeriod,
  CalibrationSnapshot,
  MinuteSnapshot,
  RollingMetric,
  SetupSnapshot,
  TickerSnapshot
} from '../types/models';

const API_BASE = '/api';

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const api = {
  getTickers: () => fetchJson<string[]>('/tickers'),
  getOverview: () => fetchJson<TickerSnapshot[]>('/overview'),
  getRollingFeed: () => fetchJson<RollingMetric[]>('/feeds/rolling'),
  getSetupFeed: () => fetchJson<SetupSnapshot[]>('/feeds/setups'),
  getMinuteFeed: () => fetchJson<MinuteSnapshot[]>('/feeds/minutes'),
  
  getCalibrationState: () => fetchJson<ActiveCalibrationState | null>('/calibration/state'),
  getCalibrationPeriods: () => fetchJson<ArchivePeriod[]>('/calibration/periods'),
  getActiveSnapshot: () => fetchJson<CalibrationSnapshot | null>('/calibration/active-snapshot'),
  
  previewCalibration: (periodId: string, archiveHours: number) =>
    fetchJson<CalibrationSnapshot>('/calibration/preview', {
      method: 'POST',
      body: JSON.stringify({ period_id: periodId, archive_hours: archiveHours }),
    }),
    
  activateCalibration: (periodId: string, archiveHours: number) =>
    fetchJson<{ snapshot: CalibrationSnapshot; state: ActiveCalibrationState }>('/calibration/activate', {
      method: 'POST',
      body: JSON.stringify({ period_id: periodId, archive_hours: archiveHours }),
    }),
    
  setCalibrationMode: (mode: 'manual' | 'auto', archiveHours: number) =>
    fetchJson<{ state: ActiveCalibrationState; snapshot?: CalibrationSnapshot; auto_error?: string }>('/calibration/mode', {
      method: 'POST',
      body: JSON.stringify({ mode, archive_hours: archiveHours }),
    }),
};
