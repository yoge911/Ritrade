import { ReactNode } from 'react';

export interface Column<T> {
  name: string;
  label: string;
  align?: 'left' | 'right' | 'center';
  format?: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  data: T[];
  columns: Column<T>[];
  rowKey: (row: T, index: number) => string;
}

export function DataTable<T>({ data, columns, rowKey }: DataTableProps<T>) {
  if (data.length === 0) {
    return <div className="text-muted text-sm py-4">No data available</div>;
  }

  return (
    <div className="data-table-wrapper">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.name}
                style={{ textAlign: col.align || 'left' }}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, index) => (
            <tr key={rowKey(row, index)}>
              {columns.map((col) => (
                <td
                  key={col.name}
                  style={{ textAlign: col.align || 'left' }}
                  className={col.align === 'right' ? 'font-mono text-sm' : 'text-sm'}
                >
                  {col.format ? col.format(row) : (row as any)[col.name]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
