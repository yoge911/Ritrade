import { ReactNode } from 'react';

export function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <div className="dashboard-container">
      {children}
    </div>
  );
}
