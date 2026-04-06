export interface TickerSnapshot {
  ticker: string;
  rolling: RollingMetric | null;
  latest_trade: LatestTrade | null;
  setup: SetupSnapshot | null;
  minute: MinuteSnapshot | null;
}

export interface RollingMetric {
  ticker?: string;
  timestamp?: string;
  activity_score?: number | string | null;
  trades?: number | string | null;
  volume?: number | string | null;
  wap?: number | string | null;
  std_dev?: number | string | null;
  slope?: number | string | null;
  is_qualified_activity?: boolean;
}

export interface LatestTrade {
  price?: number;
  qty?: number;
  time?: number;
  is_buyer_maker?: boolean;
}

export interface SetupSnapshot {
  ticker?: string;
  setup_start_time?: string;
  setup_end_time?: string;
  timestamp?: string;
  qualification_duration_ms?: number | string | null;
  activity_score?: number | string | null;
  trades?: number | string | null;
  volume?: number | string | null;
  trigger_reason?: string;
}

export interface MinuteSnapshot {
  ticker?: string;
  timestamp?: string;
  trades?: number | string | null;
  volume?: number | string | null;
  avg_price?: number | string | null;
}

export interface ArchivePeriod {
  period_id: string;
  nominal_end_time: string;
  effective_end_time: string;
}

export interface ActiveCalibrationState {
  active_run_id: string | null;
  active_archive_period_id: string | null;
  active_archive_period_end: string | null;
  active_archive_hours: number | null;
  activation_mode: 'manual' | 'auto';
  auto_archive_hours?: number;
}

export interface Thresholds {
  min_volume_threshold: number;
  max_volume_threshold: number;
  min_trade_count: number;
  max_trade_count: number;
  min_std_dev: number;
  max_std_dev: number;
}

export interface CalibrationSource {
  first_event_time_ms: number | null;
  last_event_time_ms: number | null;
}

export interface TickerCalibration {
  ticker: string;
  lookback_duration_minutes: number;
  window_ms: number;
  sampling_interval_ms: number;
  sample_count: number;
  lower_percentile: number;
  upper_percentile: number;
  thresholds: Thresholds;
  source: CalibrationSource;
  entry_status: string;
}

export interface CalibrationSnapshot {
  tickers: TickerCalibration[];
}

export interface MonitorSnapshotPayload {
  overview: TickerSnapshot[];
  rolling: RollingMetric[];
  setups: SetupSnapshot[];
  minutes: MinuteSnapshot[];
  calibrationState: ActiveCalibrationState | null;
}

export interface MonitorWsMessage {
  type: 'snapshot' | 'update';
  payload: MonitorSnapshotPayload;
}
