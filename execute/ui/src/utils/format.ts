export function formatPrice(value?: number | null): string {
  return value == null ? '—' : `$${value.toFixed(2)}`;
}

export function formatPnl(value?: number | null): string {
  if (value == null) {
    return '—';
  }
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}`;
}

export function formatMetric(value?: number | null, digits = 2): string {
  return value == null ? '—' : value.toFixed(digits);
}

export function fallbackText(value?: string | null): string {
  return value && value.trim().length > 0 ? value : '—';
}
