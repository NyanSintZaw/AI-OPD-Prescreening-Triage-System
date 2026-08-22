import type { ReactNode } from 'react';
import { cx } from './cx';

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Cell renderer; defaults to `row[key]`. */
  render?: (row: T) => ReactNode;
  align?: 'left' | 'right' | 'center';
  width?: string | number;
}
export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** Shown when rows is empty. */
  empty?: ReactNode;
  /** `compact` = 36px rows for the nurse queue. */
  density?: 'normal' | 'compact';
  caption?: string;
}
/** Dense portal table. Numbers are tabular; the only colour on the page should be the triage Badge inside it. */
export function DataTable<T extends Record<string, any>>({ columns, rows, rowKey, onRowClick, empty = 'Nothing here yet.', density = 'normal', caption }: DataTableProps<T>) {
  return (
    <div className="mali-table__wrap">
      <table className={cx('mali-table', `mali-table--${density}`, onRowClick && 'mali-table--clickable')}>
        {caption && <caption className="mali-table__caption">{caption}</caption>}
        <thead><tr>{columns.map((c) => <th key={c.key} style={{ textAlign: c.align, width: c.width }}>{c.header}</th>)}</tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td className="mali-table__empty" colSpan={columns.length}>{empty}</td></tr>}
          {rows.map((r) => (
            <tr key={rowKey(r)} onClick={onRowClick ? () => onRowClick(r) : undefined} tabIndex={onRowClick ? 0 : undefined}>
              {columns.map((c) => <td key={c.key} style={{ textAlign: c.align }}>{c.render ? c.render(r) : r[c.key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
