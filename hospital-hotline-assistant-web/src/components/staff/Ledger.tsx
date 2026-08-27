/**
 * A label-and-value list. The form a record takes when there is nothing to
 * compare it against — one HIS visit, one paired instrument.
 *
 * Blank is drawn as an explicit em dash in a recessive tone rather than an
 * empty cell, because on the HIS panel the whole point is which fields the
 * hospital already had and which ones our write-back filled in. An empty cell
 * cannot tell "not recorded" from "not rendered".
 */
import type { ReactNode } from 'react';

export function Ledger({
  children,
  className = '',
}: {
  children: ReactNode;
  /** For a caller that needs its own column measure — a findings list wants
   *  the value beside its label, not pinned to the far edge of a 78rem card. */
  className?: string;
}) {
  return <div className={`ledger ${className}`}>{children}</div>;
}

export function LedgerRow({
  label,
  value,
  /** Which write-back stage filled this in, where that is the question. */
  stage,
}: {
  label: string;
  value: unknown;
  stage?: string;
}) {
  const filled = value !== null && value !== undefined && value !== '';
  return (
    <div className={`ledger-row ${filled ? 'filled' : 'blank'}`}>
      <span className="ledger-label">
        {label}
        {stage ? <span className={`ledger-stage ledger-stage-${stage}`}>{stage}</span> : null}
      </span>
      <span className="ledger-value">{filled ? String(value) : '—'}</span>
    </div>
  );
}
