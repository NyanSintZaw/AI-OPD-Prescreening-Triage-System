/**
 * Chart primitives for the staff dashboard.
 *
 * Presentational only — no i18n, no API, no colour decisions beyond the two
 * the design system already made (one teal for magnitude, the MOPH ramp for
 * acuity). Every form here was picked from the data's *job*, and two rules
 * decided the whole file:
 *
 *  1. **Length is not the magnitude channel.** A ranked bar chart whose values
 *     are all 1 draws six identical full-width bars — the ink says "these
 *     differ" and the data says they don't. Position on a common axis (dot
 *     plot) degrades honestly: equal values stack into a column.
 *  2. **At booth volumes you can count the patients.** A prescreening kiosk
 *     sees tens of people a day, not thousands. Below `UNIT_CAP` the right
 *     form is one mark per patient — countable, hoverable, and it cannot
 *     overstate precision the way a bar of length 3 does.
 *
 * The MOPH ramp fails the colourblind-separation check between levels 1 and 2
 * (ΔE 13.1 for *normal* vision, floor is 15) and levels 3 and 4 sit under 3:1
 * on white. So acuity marks always carry the digit — `TriageBadge` is the only
 * way a level is drawn anywhere in this file.
 */
import { useId, useRef, useState } from 'react';
import { TriageBadge } from '../staff/TriageBadge';

/** Above this many units the strip stops being countable and becomes a mass. */
const UNIT_CAP = 60;

/** Head-room above the tallest point, in viewBox units, so a peak never
 *  touches the panel edge. */
const TOP_PAD = 8;

/** Floor-room below zero. Without it a flat run of zeroes is drawn *on* the
 *  closing edge of the area and reads as a line that ran off the chart,
 *  rather than as a series sitting at zero. */
const BOTTOM_PAD = 6;

const nf = new Intl.NumberFormat();

/**
 * Round tick values covering `max`, and the top one to scale the plot against.
 *
 * The trend charts had no y axis at all: a reader could name the peak, because
 * that one point is direct-labelled, and nothing else without hovering. Ticks
 * turn the whole shape into something readable at a glance, which is most of
 * what the height of these cards was already being spent on.
 *
 * Steps are forced to whole numbers because every series on this board is a
 * count of patients. A 0 / 0.5 / 1 axis is arithmetically fine and clinically
 * nonsense.
 */
function niceTicks(max: number, target = 4): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / target;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const nice = [1, 2, 2.5, 5, 10].find((m) => m * magnitude >= raw) ?? 10;
  const step = Math.max(1, Math.round(nice * magnitude));
  const top = Math.ceil(max / step) * step;
  const out: number[] = [];
  for (let v = 0; v <= top; v += step) out.push(v);
  return out;
}

/** Series → SVG polyline points in a 0–100 box, plus the last point's spot.
 *
 *  The box is drawn with `preserveAspectRatio="none"`, which stretches it to
 *  whatever width the panel has. That distorts anything round, so every dot in
 *  this file is a CSS element positioned at these percentages instead of an
 *  SVG `<circle>` — a circle in a stretched viewBox renders as an ellipse.
 */
function plot(values: number[], max: number) {
  const span = Math.max(1, values.length - 1);
  const points = values.map((value, i) => {
    const x = (i / span) * 100;
    const y = TOP_PAD + (1 - value / (max || 1)) * (100 - TOP_PAD - BOTTOM_PAD);
    return { x, y, value, i };
  });
  return points;
}

const toPath = (points: Array<{ x: number; y: number }>) =>
  points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');

/* ── Sparkline ────────────────────────────────────────────────────────────
   The trend channel on a stat tile. Not a chart in its own right: no axis,
   no labels, one hue — it exists so the number above it is read as "12, and
   rising" rather than "12, out of nowhere". */

export function Sparkline({ values, label }: { values: number[]; label: string }) {
  const max = Math.max(1, ...values);
  const points = plot(values, max);
  const last = points[points.length - 1];
  if (points.length < 2) return null;
  // Nothing happened. A flat run of zeroes is drawn on the floor and still
  // reads as a series — "0, and it has been 0" is what the value already says.
  if (values.every((v) => v === 0)) return null;
  return (
    <div className="spark" role="img" aria-label={label}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <path className="spark-area" d={`${toPath(points)} L100,100 L0,100 Z`} />
        <path className="spark-line" d={toPath(points)} vectorEffect="non-scaling-stroke" />
      </svg>
      <span className="spark-dot" style={{ insetBlockStart: `${last.y}%` }} aria-hidden="true" />
    </div>
  );
}

/* ── Unit strip ───────────────────────────────────────────────────────────
   One mark per patient, most-urgent first. The form the queue actually has:
   you can count it, and each unit is a patient you can open. */

export interface Unit {
  id: string;
  level?: number | null;
  label: string;
}

export function UnitStrip({
  units,
  onSelect,
}: {
  units: Unit[];
  onSelect?: (id: string) => void;
}) {
  const shown = units.slice(0, UNIT_CAP);
  const rest = units.length - shown.length;
  return (
    <div className="unit-strip">
      {shown.map((unit) =>
        onSelect ? (
          <button
            key={unit.id}
            type="button"
            className="unit"
            title={unit.label}
            aria-label={unit.label}
            onClick={() => onSelect(unit.id)}
          >
            <TriageBadge level={unit.level} />
          </button>
        ) : (
          <span key={unit.id} className="unit" title={unit.label}>
            <TriageBadge level={unit.level} />
          </span>
        ),
      )}
      {rest > 0 ? <span className="unit-rest">+{nf.format(rest)}</span> : null}
    </div>
  );
}

/* ── Share strip ──────────────────────────────────────────────────────────
   Part-to-whole in one row. The five acuity levels used to get five tracks
   each, so a day where everyone was level 4 drew four empty rails and one
   fill. Here a level with no patients simply isn't in the strip; the legend
   still lists it, which is where a zero belongs. */

export interface Share {
  level: number;
  name: string;
  count: number;
}

export function ShareStrip({ rows, total }: { rows: Share[]; total: number }) {
  const present = rows.filter((r) => r.count > 0);
  return (
    <div className="share">
      <div className="share-strip" role="img" aria-label={present
        .map((r) => `${r.name} ${r.count}`)
        .join(', ')}>
        {present.map((row) => (
          <span
            key={row.level}
            className={`share-seg triage-level-${row.level}`}
            style={{ flexGrow: row.count }}
            title={`${row.name} — ${nf.format(row.count)}`}
          />
        ))}
      </div>
      <ul className="share-legend">
        {rows.map((row) => (
          <li key={row.level} className={row.count === 0 ? 'is-zero' : ''}>
            <TriageBadge level={row.level} />
            <span className="share-name">{row.name}</span>
            <span className="share-count">{nf.format(row.count)}</span>
            <span className="share-pct">
              {total ? `${Math.round((row.count / total) * 100)}%` : '—'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ── Dot plot ─────────────────────────────────────────────────────────────
   Ranked magnitude, without bars. Cleveland's result — position along a
   common scale is read more accurately than length — is the reason, but the
   practical one is failure behaviour: when every department has the same
   count the dots line up in a column and say so, where equal-length bars say
   nothing at all. */

export interface DotRow {
  key: string;
  label: string;
  value: number;
}

export function DotPlot({ rows, axisLabel }: { rows: DotRow[]; axisLabel: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="dotplot">
      <ul className="dotplot-rows">
        {rows.map((row) => (
          <li key={row.key} className="dotplot-row">
            <span className="dotplot-label" title={row.label}>
              {row.label}
            </span>
            <span className="dotplot-track">
              <span
                className="dotplot-dot"
                style={{ insetInlineStart: `${(row.value / max) * 100}%` }}
                title={`${row.label} — ${nf.format(row.value)}`}
              />
            </span>
            <span className="dotplot-value">{nf.format(row.value)}</span>
          </li>
        ))}
      </ul>
      <div className="dotplot-axis" aria-hidden="true">
        <span>0</span>
        <span className="dotplot-axis-title">{axisLabel}</span>
        <span>{nf.format(max)}</span>
      </div>
    </div>
  );
}

/* ── Trend area ───────────────────────────────────────────────────────────
   A count over an ordered axis — arrivals through today, sessions across the
   window. Twenty-four columns spent ten of them on hours the booth is shut,
   and drew every quiet hour as a visible stick; an area is one shape, and the
   part of the axis that hasn't happened yet is drawn recessive so an empty
   afternoon reads as "not yet" rather than "nobody came". */

export interface TrendPoint {
  /** Tick label for this slot. */
  tick: string;
  value: number;
}

export function TrendArea({
  points: series,
  /** Index of the last slot that has finished. Everything after it is drawn
   *  recessive. Pass `points.length - 1` to draw the whole series as settled. */
  liveUntil,
  tickEvery = 3,
  label,
  formatPoint,
}: {
  points: TrendPoint[];
  liveUntil: number;
  tickEvery?: number;
  label: string;
  formatPoint: (point: TrendPoint) => string;
}) {
  const clipId = useId();
  const plotRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const ticks = niceTicks(Math.max(1, ...series.map((p) => p.value)));
  const max = ticks[ticks.length - 1];
  const points = plot(
    series.map((p) => p.value),
    max,
  );
  const peak = points.reduce((best, p) => (p.value > best.value ? p : best), points[0]);
  // Where the settled part ends, as a fraction of the axis — the clip edge
  // that splits what happened from what is still to come.
  const liveX = (Math.min(Math.max(liveUntil, 0), series.length - 1) / Math.max(1, series.length - 1)) * 100;

  const active = hover === null ? null : points[hover];

  const pick = (clientX: number) => {
    const box = plotRef.current?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    const ratio = (clientX - box.left) / box.width;
    setHover(Math.min(points.length - 1, Math.max(0, Math.round(ratio * (points.length - 1)))));
  };

  if (points.length < 2) return null;

  return (
    <div className="trend">
      <div className="trend-grid">
        <div className="trend-scale" aria-hidden="true">
          {[...ticks].reverse().map((v) => (
            <span key={v}>{nf.format(v)}</span>
          ))}
        </div>
      <div
        className="trend-plot"
        ref={plotRef}
        role="img"
        tabIndex={0}
        aria-label={label}
        onPointerMove={(e) => pick(e.clientX)}
        onPointerLeave={() => setHover(null)}
        onFocus={() => setHover((h) => (h === null ? peak.i : h))}
        onBlur={() => setHover(null)}
        onKeyDown={(e) => {
          if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
          e.preventDefault();
          setHover((h) => {
            const next = (h === null ? peak.i : h) + (e.key === 'ArrowRight' ? 1 : -1);
            return Math.min(points.length - 1, Math.max(0, next));
          });
        }}
      >
        {/* Solid hairlines, never dashed: a dashed rule reads as a threshold
            or a projection when it is only a grid. */}
        {ticks.map((v, i) => (
          <span
            key={v}
            className="trend-gridline"
            style={{ insetBlockStart: `${(1 - v / max) * 100}%` }}
            aria-hidden="true"
            data-base={i === 0 || undefined}
          />
        ))}
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            {/* The clip is what makes settled and pending one continuous shape
                in two weights, rather than two series needing a legend. */}
            <clipPath id={clipId}>
              <rect x="0" y="0" width={liveX} height="100" />
            </clipPath>
          </defs>
          <path className="trend-future" d={`${toPath(points)} L100,100 L0,100 Z`} />
          <path className="trend-future-line" d={toPath(points)} vectorEffect="non-scaling-stroke" />
          <g clipPath={`url(#${clipId})`}>
            <path className="trend-fill" d={`${toPath(points)} L100,100 L0,100 Z`} />
            <path className="trend-line" d={toPath(points)} vectorEffect="non-scaling-stroke" />
          </g>
        </svg>

        {peak.value > 0 ? (
          <span
            className={`trend-peak ${peak.x < 8 ? 'at-start' : ''} ${peak.x > 92 ? 'at-end' : ''}`}
            style={{ insetInlineStart: `${peak.x}%`, insetBlockStart: `${peak.y}%` }}
            aria-hidden="true"
          >
            {nf.format(peak.value)}
          </span>
        ) : null}

        {active ? (
          <>
            <span
              className="trend-crosshair"
              style={{ insetInlineStart: `${active.x}%` }}
              aria-hidden="true"
            />
            <span
              className="trend-marker"
              style={{ insetInlineStart: `${active.x}%`, insetBlockStart: `${active.y}%` }}
              aria-hidden="true"
            />
            <span
              className="trend-readout"
              style={{ insetInlineStart: `${active.x}%` }}
              aria-hidden="true"
            >
              {formatPoint(series[active.i])}
            </span>
          </>
        ) : null}
      </div>
      </div>
      <div className="trend-axis" aria-hidden="true">
        {/* Ticks on a fixed stride only. Forcing a label onto the final slot
            put it a single step from its neighbour whenever the series length
            was not a multiple of the stride, and the two overlapped. */}
        {series.map((p, i) => {
          if (i % tickEvery !== 0) return null;
          const at = (i / (series.length - 1)) * 100;
          return (
            <span
              key={p.tick}
              className={at < 4 ? 'at-start' : at > 96 ? 'at-end' : ''}
              style={{ insetInlineStart: `${at}%` }}
            >
              {p.tick}
            </span>
          );
        })}
      </div>
    </div>
  );
}

/* ── Heatmap ──────────────────────────────────────────────────────────────
   Magnitude on a grid. Used twice on the admin board, because both of its
   grid-shaped questions are the same question — *where is the mass*:
   arrivals by weekday × hour, and the proposed-vs-confirmed routing matrix.

   Four steps, not a continuous gradient. Past about seven bins adjacent
   classes blur, and a reader cannot decode a shade they cannot name. Zero
   gets its own neutral rather than the palest step, because "nobody came" is
   a state and not a small number. Steps are quartiles of the observed range,
   so one busy cell doesn't flatten everything else into the lightest class.

   Cells carry their value as an `aria-label`, not only a `title` — a value
   reachable *only* by hovering is a value keyboard and screen-reader users
   do not have. */

export interface HeatCell {
  row: number;
  col: number;
  value: number;
}

export function Heatmap({
  cells,
  rowLabels,
  colLabels,
  colTick = 1,
  cellLabel,
  maxLabel,
}: {
  cells: HeatCell[];
  rowLabels: string[];
  colLabels: string[];
  /** Render every Nth column label — twenty-four hour labels do not fit. */
  colTick?: number;
  cellLabel: (row: number, col: number, value: number) => string;
  /** Legend caption for the dark end. */
  maxLabel: (max: number) => string;
}) {
  const max = Math.max(0, ...cells.map((c) => c.value));
  const byKey = new Map(cells.map((c) => [`${c.row}:${c.col}`, c.value]));
  const step = (v: number) => (v === 0 ? 0 : Math.min(4, Math.ceil((v / (max || 1)) * 4)));

  return (
    <div className="heatmap">
      <div
        className="heatmap-grid"
        style={{ gridTemplateColumns: `auto repeat(${colLabels.length}, minmax(0, 1fr))` }}
      >
        <span aria-hidden="true" />
        {colLabels.map((label, c) => (
          <span key={`c${c}`} className="heatmap-col-label" aria-hidden="true">
            {c % colTick === 0 ? label : ''}
          </span>
        ))}
        {rowLabels.map((rowLabel, r) => (
          <Row key={`r${r}`}>
            <span className="heatmap-row-label">{rowLabel}</span>
            {colLabels.map((_, c) => {
              const value = byKey.get(`${r}:${c}`) ?? 0;
              return (
                <span
                  key={`${r}:${c}`}
                  className={`heatmap-cell heat-${step(value)}`}
                  role="img"
                  aria-label={cellLabel(r, c, value)}
                  title={cellLabel(r, c, value)}
                />
              );
            })}
          </Row>
        ))}
      </div>
      <div className="heatmap-legend" aria-hidden="true">
        <span>0</span>
        {[0, 1, 2, 3, 4].map((s) => (
          <span key={s} className={`heatmap-key heat-${s}`} />
        ))}
        <span>{maxLabel(max)}</span>
      </div>
    </div>
  );
}

/** A grid wants its cells as direct children, so a row cannot be an element. */
function Row({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

/* ── Meter ────────────────────────────────────────────────────────────────
   The one place a filled track survives on this board. A meter is not a bar
   chart with one bar: it answers "how much of the whole", where the whole is
   a real limit the reader already knows — every explanation that could have
   been grounded, every disposition that should have reached the HIS. Nothing
   is being compared to a neighbour, so position on a common axis buys
   nothing and the track is honest.

   The unfilled part is a lighter step of the same hue rather than a grey, so
   the state reads across the whole width instead of only the filled part. */

export function Meter({
  label,
  value,
  total,
  tone = 'default',
}: {
  label: string;
  value: number;
  total: number;
  tone?: 'default' | 'warning';
}) {
  const pct = total > 0 ? (value / total) * 100 : 0;
  return (
    <div className="meter">
      <div className="meter-head">
        <span className="meter-label">{label}</span>
        <span className="meter-value">
          {total > 0 ? `${Math.round(pct)}%` : '—'}
          <span className="meter-of">
            {' '}
            {nf.format(value)}/{nf.format(total)}
          </span>
        </span>
      </div>
      <div
        className={`meter-track meter-${tone}`}
        role="img"
        aria-label={`${label} — ${nf.format(value)}/${nf.format(total)}`}
      >
        <span className="meter-fill" style={{ inlineSize: `${pct}%` }} />
      </div>
    </div>
  );
}

/* ── Funnel ───────────────────────────────────────────────────────────────
   started → reached a decision → sent to the HIS → nurse reviewed.

   Two things were wrong with the first attempt, and both were mine.

   It refused to encode magnitude at all — four equal boxes with numbers in
   them, spaced by a "33% carried through" chip that competed with the boxes
   for attention and left every card a different width. This file's rule is
   that length is not the magnitude channel, but that rule is about *ranked
   categories*, where equal values draw equal bars and say nothing. This is
   part-to-whole against a total the reader is holding — the same job
   `ShareStrip` does — and length is exactly right for it. One bar per stage,
   all measured against the first, so the drop is the picture.

   And every gap said the same wordless thing: "−2". A patient who left before
   answering, a record the HIS refused, and a case a nurse simply has not
   reached yet are three different events, and only the last is not a loss at
   all. So the caller words each drop itself; the chart just places it. */

export interface FunnelStage {
  key: string;
  label: string;
  value: number;
  /** Already worded by the caller — "6 left before a decision". The first
   *  stage has nothing above it and takes none. */
  drop?: string;
  /** A detail under the stage: how the ones that failed, failed. */
  note?: string;
}

export function Funnel({ stages }: { stages: FunnelStage[] }) {
  const total = stages[0]?.value ?? 0;
  return (
    <ol className="funnel">
      {stages.map((stage) => {
        const pct = total > 0 ? (stage.value / total) * 100 : 0;
        return (
          <li key={stage.key} className="funnel-stage">
            <div className="funnel-head">
              <span className="funnel-label">{stage.label}</span>
              <span className="funnel-value">
                {nf.format(stage.value)}
                {/* Share of the first stage, not of the one above — "67%"
                    between two middle stages was read as a share of the
                    total by everyone who saw it. */}
                <span className="funnel-share">{total > 0 ? `${Math.round(pct)}%` : '—'}</span>
              </span>
            </div>
            <div className="funnel-track">
              <span
                className="funnel-fill"
                style={{ inlineSize: `${pct}%` }}
                /* The bar restates the number beside it, so it is decoration
                   to a screen reader and noise if announced twice. */
                aria-hidden="true"
              />
            </div>
            {stage.drop || stage.note ? (
              <p className="funnel-drop">
                {stage.drop ? (
                  <span className="funnel-drop-main">
                    <span aria-hidden="true">↳</span> {stage.drop}
                  </span>
                ) : null}
                {stage.note ? <span className="funnel-note">{stage.note}</span> : null}
              </p>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

/* ── Board chrome ─────────────────────────────────────────────────────────
   Bands, panels and figures. Presentational like everything else in this
   file, and shared so a panel on the nurse board and a panel on the admin
   board are the same object rather than two that drifted apart. */

export function Band({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="dash-band">
      <header className="dash-band-head">
        <h2>{title}</h2>
        {note ? <p>{note}</p> : null}
      </header>
      <div className="dash-band-body">{children}</div>
    </section>
  );
}

export function Panel({
  title,
  subtitle,
  span,
  action,
  children,
}: {
  title: string;
  subtitle?: string;
  /** Grid columns to occupy — panels are equal-height, never masonry. */
  span?: 2 | 3;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className={`dash-panel ${span ? `dash-panel-${span}` : ''}`}>
      <header className="dash-panel-head">
        <div>
          <h3>{title}</h3>
          {subtitle ? <p className="dash-panel-sub">{subtitle}</p> : null}
        </div>
        {action}
      </header>
      <div className="dash-panel-body">{children}</div>
    </section>
  );
}

export function EmptyNote({ text }: { text: string }) {
  return <p className="dash-empty">{text}</p>;
}

/**
 * Value, optional label, signed delta and sparkline. No track, no fill bar —
 * a one-bar bar chart is a stat tile that has not realised it yet.
 *
 * The delta is deliberately **not** coloured by direction. More patients at a
 * screening booth is not good news or bad news, and painting an increase
 * green would assert that it is. Where a number does need to raise its hand,
 * `tone="attention"` says "look here" without claiming which way is up.
 */
export function Figure({
  label,
  value,
  unit,
  delta,
  spark,
  hint,
  hero,
  tile,
  tone,
}: {
  /** Omitted where the panel heading already names the number. */
  label?: string;
  value: string;
  unit?: string;
  delta?: { text: string; up: boolean | null } | null;
  spark?: { values: number[]; label: string } | null;
  hint?: string | null;
  hero?: boolean;
  /** Draw as its own card. Off inside a panel, which is already a card. */
  tile?: boolean;
  tone?: 'attention';
}) {
  return (
    <div
      className={`figure ${hero ? 'figure-hero' : ''} ${tile ? 'figure-tile' : ''} ${
        tone === 'attention' ? 'figure-attention' : ''
      }`}
    >
      {label ? <p className="figure-label">{label}</p> : null}
      <p className="figure-value">
        {value}
        {unit ? <span className="figure-unit">{unit}</span> : null}
      </p>
      {delta ? (
        <p className="figure-delta">
          {delta.up === null ? null : (
            <span className="figure-delta-arrow" aria-hidden="true">
              {delta.up ? '↑' : '↓'}
            </span>
          )}
          {delta.text}
        </p>
      ) : null}
      {spark && spark.values.length > 1 ? (
        <Sparkline values={spark.values} label={spark.label} />
      ) : null}
      {hint ? <p className="figure-hint">{hint}</p> : null}
    </div>
  );
}

/**
 * A handful of labelled counts — why an explanation was not grounded, what the
 * validator caught.
 *
 * Deliberately not a dot plot. These lists run to one to four rows with counts
 * in the single digits, where a positional chart encodes nothing and its label
 * column truncates reasons that are written as sentences. The reason IS the
 * content here; the number is the footnote.
 */
export function ReasonList({
  rows,
}: {
  rows: Array<{ key: string; label: string; value: number }>;
}) {
  return (
    <ul className="dash-reasons">
      {rows.map((row) => (
        <li key={row.key}>
          <span className="dash-reason-label">{row.label}</span>
          <span className="dash-reason-count">{nf.format(row.value)}</span>
        </li>
      ))}
    </ul>
  );
}
