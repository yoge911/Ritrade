import type { RollingMetric, SetupSnapshot } from '../types/models';

export function formatMetric(value: unknown, digits: number = 2): string {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  if (typeof value === 'number') {
    return value.toFixed(digits);
  }
  const number = parseFloat(String(value));
  if (isNaN(number)) {
    return String(value);
  }
  return number.toFixed(digits);
}

export function formatDurationMs(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  const ms = parseInt(String(value), 10);
  if (isNaN(ms)) {
    return String(value);
  }
  return `${(ms / 1000).toFixed(0)}s`;
}

export function signalLabel(row: Partial<RollingMetric & SetupSnapshot>): string {
  if (row.is_qualified_activity) {
    return 'Qualified';
  }
  const score = row.activity_score;
  const numericScore = parseFloat(String(score));
  if (isNaN(numericScore)) {
    return 'Watching';
  }
  if (numericScore >= 0.3) {
    return 'Developing';
  }
  return 'Quiet';
}

export function signalClass(row: Partial<RollingMetric & SetupSnapshot>): string {
  if (row.is_qualified_activity) {
    return 'signal-hot';
  }
  const score = row.activity_score;
  const numericScore = parseFloat(String(score));
  if (isNaN(numericScore)) {
    return 'signal-cold';
  }
  if (numericScore >= 0.3) {
    return 'signal-warm';
  }
  return 'signal-cold';
}

export function formatIsoTime(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value.replace('Z', '+00:00'));
  return formatClockTime(d);
}

export function formatEventTimeMs(value?: number | null): string {
  if (value == null) return '—';
  return formatClockTime(new Date(value));
}

export function formatClockTime(date: Date): string {
  if (isNaN(date.getTime())) return '—';
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  const h = String(date.getHours()).padStart(2, '0');
  const m = String(date.getMinutes()).padStart(2, '0');
  const s = String(date.getSeconds()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${h}:${m}:${s}`;
}

export function buildArchivePeriodOptionLabel(nominalEndTime: string, effectiveEndTime: string): string {
  const nomD = new Date(nominalEndTime);
  const effD = new Date(effectiveEndTime);
  const label = formatClockTime(nomD);
  if (effD < nomD) {
    return `${label} [PARTIAL]`;
  }
  return label;
}
