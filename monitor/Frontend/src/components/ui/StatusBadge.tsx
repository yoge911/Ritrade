import { memo } from 'react';

interface StatusBadgeProps {
  label: string;
  variant: 'cold' | 'warm' | 'hot';
}

export const StatusBadge = memo(function StatusBadge({ label, variant }: StatusBadgeProps) {
  return (
    <span className={`status-badge signal-${variant}`}>
      {label}
    </span>
  );
});
