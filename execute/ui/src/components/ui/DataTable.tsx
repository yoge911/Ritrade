import type { ReactNode } from 'react';

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
  rowClassName?: (row: T) => string | undefined;
}

export function DataTable<T>({ data, columns, rowKey, rowClassName }: DataTableProps<T>) {
  if (data.length === 0) {
    return <div className="table-empty">No data available</div>;
  }

  return (
    <div className="data-table-wrapper">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.name} style={{ textAlign: column.align || 'left' }}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, index) => (
            <tr key={rowKey(row, index)} className={rowClassName?.(row)}>
              {columns.map((column) => (
                <td
                  key={column.name}
                  style={{ textAlign: column.align || 'left' }}
                  className={column.align === 'right' ? 'numeric-cell' : undefined}
                >
                  {column.format ? column.format(row) : (row as Record<string, ReactNode>)[column.name]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
