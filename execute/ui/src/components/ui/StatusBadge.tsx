import clsx from 'clsx';
import type { SignalVariant } from '../../types/models';

interface StatusBadgeProps {
  label: string;
  variant: SignalVariant;
}

export function StatusBadge({ label, variant }: StatusBadgeProps) {
  return <span className={clsx('status-badge', `signal-${variant}`)}>{label}</span>;
}
