export type SignalVariant = 'cold' | 'warm' | 'hot';
export type NoticeTone = 'info' | 'success' | 'warning' | 'error';

export interface ExecutionStatus {
  ticker?: string;
  is_pinned?: boolean;
  state?: string;
  position?: string;
  live_price?: number | null;
  limit_price?: number | null;
  entry_price?: number | null;
  stop_price?: number | null;
  target_price?: number | null;
  pnl?: number | null;
  zone?: string;
  quantity?: number | null;
  risk_percent?: number | null;
  reward_percent?: number | null;
  initiated_by?: string;
  control_mode?: string;
  entry_strategy?: string;
  exit_strategy?: string;
  entry_decision?: string;
  exit_decision?: string;
  decision_reason?: string;
  manual_override_active?: boolean;
  strategy_state?: Record<string, unknown>;
  stop_mode?: string;
  last_update?: string;
}

export interface ExecutionActivitySnapshot {
  timestamp?: string | null;
  is_qualified_activity?: boolean;
  activity_score?: number | null;
  trades?: number | null;
  volume?: number | null;
  wap?: number | null;
  std_dev?: number | null;
  slope?: number | null;
}

export interface ExecutionPinnedTicker {
  ticker: string;
  status: ExecutionStatus;
  activity: ExecutionActivitySnapshot;
  badge_label: string;
  score_class: SignalVariant;
  pnl_class: 'profit' | 'loss' | 'neutral';
  last_timestamp: string;
}

export interface ExecutionSignalRow {
  ticker: string;
  timestamp?: string | null;
  qualified: 'Yes' | 'No';
  activity_score?: number | null;
  trades?: number | null;
  volume?: number | null;
  wap?: number | null;
  std_dev?: number | null;
  slope?: number | null;
  minute_timestamp?: string | null;
  minute_trades?: number | null;
  minute_volume?: number | null;
  minute_avg_price?: number | null;
  is_pinned: boolean;
}

export interface ExecutionMinuteRow extends ExecutionSignalRow {}

export interface ExecutionDashboardSnapshot {
  tickers: string[];
  pinned: ExecutionPinnedTicker[];
  activityRows: ExecutionSignalRow[];
  minuteRows: ExecutionMinuteRow[];
}

export interface ExecutionWsMessage {
  type: 'snapshot' | 'update';
  payload: ExecutionDashboardSnapshot;
}

export interface ExecutionCommandRequest {
  action: string;
  ticker: string;
  side?: string;
  limit_price?: number;
  initiated_by?: string;
  control_mode?: string;
  stop_price?: number;
}

export interface CommandResponse {
  ok: boolean;
  payload: ExecutionCommandRequest;
}

export interface NoticeState {
  tone: NoticeTone;
  message: string;
}
