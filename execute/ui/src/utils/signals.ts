import type { ExecutionCommandRequest, ExecutionSignalRow, ExecutionStatus, NoticeState, SignalVariant } from '../types/models';

export function scoreVariant(score?: number | null): SignalVariant {
  if (typeof score !== 'number') {
    return 'cold';
  }
  if (score >= 0.6) {
    return 'hot';
  }
  if (score >= 0.3) {
    return 'warm';
  }
  return 'cold';
}

export function isPositiveSignal(row: ExecutionSignalRow): boolean {
  return row.qualified === 'Yes' || (typeof row.activity_score === 'number' && row.activity_score >= 0.3);
}

export function buildManualOrderCommand(
  ticker: string,
  side: 'long' | 'short',
  status: ExecutionStatus,
): { command?: ExecutionCommandRequest; notice?: NoticeState } {
  if (status.live_price == null) {
    return {
      notice: {
        tone: 'warning',
        message: `${ticker} has no live price yet.`,
      },
    };
  }

  return {
    command: {
      action: 'place_limit_order',
      ticker: ticker.toLowerCase(),
      side,
      limit_price: status.live_price,
      initiated_by: 'manual',
      control_mode: 'manual',
    },
  };
}

export function buildTrailingStopCommand(
  ticker: string,
  status: ExecutionStatus,
): { command?: ExecutionCommandRequest; notice?: NoticeState } {
  if (status.live_price == null || (status.position !== 'long' && status.position !== 'short')) {
    return {
      notice: {
        tone: 'warning',
        message: `${ticker} needs an active trade and live price for trailing stop.`,
      },
    };
  }

  const trailGap = 0.0015;
  const stopPrice = status.position === 'long'
    ? status.live_price * (1 - trailGap)
    : status.live_price * (1 + trailGap);

  return {
    command: {
      action: 'modify_stop',
      ticker: ticker.toLowerCase(),
      stop_price: Number(stopPrice.toFixed(2)),
    },
  };
}
