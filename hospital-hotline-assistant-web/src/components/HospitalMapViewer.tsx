/**
 * HospitalMapViewer
 * Renders the floor-map.svg directly with an SVG route overlay.
 * Uses an A* grid pathfinder ported from public/hospital-map/app.js.
 */
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

// ── Map constants ──────────────────────────────────────────────────────────────
const MAP_W = 637;
const MAP_H = 454;
const CELL = 4;
const WALL_PAD = 2.0;
const TURN_COST = 0.45;
const PX_PER_M = 8;
const WALK_SPEED = 55; // m/min

// ── Wall geometry (extracted from floor plan) ─────────────────────────────────
const WALLS = [{"x1":361,"y1":302,"x2":629,"y2":302,"w":10},{"x1":104,"y1":302,"x2":323,"y2":302,"w":10},{"x1":230,"y1":449,"x2":637,"y2":449,"w":10},{"x1":167,"y1":449,"x2":0,"y2":449,"w":10},{"x1":5,"y1":307,"x2":5,"y2":444,"w":10},{"x1":318,"y1":169,"x2":318,"y2":307,"w":10},{"x1":5,"y1":169,"x2":5.00001,"y2":307,"w":10},{"x1":323,"y1":174,"x2":41,"y2":174,"w":10},{"x1":422,"y1":93,"x2":202,"y2":93,"w":10},{"x1":637,"y1":93,"x2":521,"y2":93,"w":10},{"x1":631,"y1":174,"x2":361,"y2":174,"w":10},{"x1":80,"y1":93,"x2":0,"y2":93,"w":10},{"x1":1085,"y1":5,"x2":4,"y2":5,"w":10},{"x1":211,"y1":93,"x2":123,"y2":93,"w":10},{"x1":207,"y1":0,"x2":207,"y2":88,"w":10},{"x1":5,"y1":0,"x2":5,"y2":88,"w":10},{"x1":474,"y1":0,"x2":474,"y2":97,"w":10},{"x1":366,"y1":252,"x2":366,"y2":307,"w":10},{"x1":366,"y1":169,"x2":366,"y2":224,"w":10},{"x1":60,"y1":174,"x2":-13,"y2":174,"w":10},{"x1":-12,"y1":302,"x2":60,"y2":302,"w":10},{"x1":634,"y1":5,"x2":634,"y2":398,"w":10},{"x1":593.5,"y1":307,"x2":593.5,"y2":360,"w":3},{"x1":519.5,"y1":307,"x2":519.5,"y2":360,"w":3},{"x1":449.5,"y1":307,"x2":449.5,"y2":360,"w":3},{"x1":555.5,"y1":307,"x2":555.5,"y2":360,"w":3},{"x1":484.5,"y1":307,"x2":484.5,"y2":360,"w":3},{"x1":634,"y1":430,"x2":634,"y2":454,"w":10}];
const BLOCKERS = [{ x: 126, y: 302, width: 154, height: 39, padding: 5 }];

// ── Location registry ──────────────────────────────────────────────────────────
export const LOCATIONS = {
  entrance:         { labelKey: 'mapDeptEntrance',        x: 198, y: 438, group: 'Access',     type: 'entry'     },
  publicWaiting:    { labelKey: 'mapDeptPublicWaiting',   x: 310, y: 386, group: 'Access',     type: 'hallway'   },
  mainHallway:      { labelKey: 'mapDeptMainHallway',     x: 342, y: 134, group: 'Access',     type: 'hallway'   },
  counter:          { labelKey: 'mapDeptCounter',         x: 198, y: 350, group: 'Service',    type: 'service'   },
  emergency:        { labelKey: 'mapDeptEmergency',       x: 82,  y: 314, group: 'Emergency',  type: 'emergency' },
  opd:              { labelKey: 'mapDeptOpd',             x: 374, y: 238, group: 'Department', type: 'room'      },
  neurology:        { labelKey: 'mapDeptNeurology',       x: 106, y: 106, group: 'Department', type: 'room'      },
  cardiology:       { labelKey: 'mapDeptCardiology',      x: 450, y: 106, group: 'Department', type: 'room'      },
  pediatrics:       { labelKey: 'mapDeptPediatrics',      x: 502, y: 106, group: 'Department', type: 'room'      },
  orthopedics:      { labelKey: 'mapDeptOrthopedics',     x: 466, y: 366, group: 'Clinic',     type: 'room'      },
  gynecology:       { labelKey: 'mapDeptGynecology',      x: 502, y: 366, group: 'Clinic',     type: 'room'      },
  gastroenterology: { labelKey: 'mapDeptGastroenterology',x: 538, y: 366, group: 'Clinic',     type: 'room'      },
  ent:              { labelKey: 'mapDeptEnt',             x: 574, y: 366, group: 'Clinic',     type: 'room'      },
  teeth:            { labelKey: 'mapDeptTeeth',           x: 614, y: 366, group: 'Clinic',     type: 'room'      },
} as const;

type LocationKey = keyof typeof LOCATIONS;
const GROUP_ORDER = ['Access', 'Service', 'Emergency', 'Department', 'Clinic'];

// ── Pathfinder (pure functions, no globals) ───────────────────────────────────
const COLS = Math.ceil(MAP_W / CELL);
const ROWS = Math.ceil(MAP_H / CELL);

function ptSegDist(px: number, py: number, w: { x1: number; y1: number; x2: number; y2: number }) {
  const dx = w.x2 - w.x1, dy = w.y2 - w.y1;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(px - w.x1, py - w.y1);
  const t = Math.max(0, Math.min(1, ((px - w.x1) * dx + (py - w.y1) * dy) / len2));
  return Math.hypot(px - (w.x1 + t * dx), py - (w.y1 + t * dy));
}

function isBlockedPt(x: number, y: number, pad = WALL_PAD) {
  if (x < 0 || y < 0 || x > MAP_W || y > MAP_H) return true;
  for (const b of BLOCKERS) {
    const p = b.padding;
    if (x >= b.x - p && x <= b.x + b.width + p && y >= b.y - p && y <= b.y + b.height + p) return true;
  }
  for (const w of WALLS) {
    const r = w.w / 2 + pad;
    if (x < Math.min(w.x1, w.x2) - r || x > Math.max(w.x1, w.x2) + r) continue;
    if (y < Math.min(w.y1, w.y2) - r || y > Math.max(w.y1, w.y2) + r) continue;
    if (ptSegDist(x, y, w) <= r) return true;
  }
  return false;
}

function buildGrid() {
  const g: boolean[][] = Array.from({ length: ROWS }, () => Array(COLS).fill(false));
  for (let r = 0; r < ROWS; r++)
    for (let c = 0; c < COLS; c++)
      g[r][c] = isBlockedPt((c + 0.5) * CELL, (r + 0.5) * CELL);
  return g;
}

function buildPenalty(grid: boolean[][]) {
  const pen: number[][] = Array.from({ length: ROWS }, () => Array(COLS).fill(0));
  const R = 5;
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      if (grid[r][c]) { pen[r][c] = 99; continue; }
      let n = 0;
      for (let dr = -R; dr <= R; dr++)
        for (let dc = -R; dc <= R; dc++) {
          if (dc === 0 && dr === 0) continue;
          const nr = r + dr, nc = c + dc;
          if (nr < 0 || nc < 0 || nr >= ROWS || nc >= COLS || grid[nr][nc]) n++;
        }
      pen[r][c] = Math.min(0.65, n * 0.01);
    }
  }
  return pen;
}

function isBlocked(grid: boolean[][], c: number, r: number) {
  return r < 0 || c < 0 || r >= ROWS || c >= COLS || grid[r][c];
}

function nearestFree(grid: boolean[][], col: number, row: number) {
  if (!isBlocked(grid, col, row)) return { col, row };
  for (let rad = 1; rad <= 40; rad++) {
    const opts: { col: number; row: number; d: number }[] = [];
    for (let dr = -rad; dr <= rad; dr++)
      for (let dc = -rad; dc <= rad; dc++) {
        if (Math.abs(dc) !== rad && Math.abs(dr) !== rad) continue;
        const nc = col + dc, nr = row + dr;
        if (!isBlocked(grid, nc, nr)) opts.push({ col: nc, row: nr, d: Math.abs(dc) + Math.abs(dr) });
      }
    if (opts.length) { opts.sort((a, b) => a.d - b.d); return { col: opts[0].col, row: opts[0].row }; }
  }
  return null;
}

const DIRS = [
  { dx: 1, dy: 0, key: 'r' }, { dx: -1, dy: 0, key: 'l' },
  { dx: 0, dy: -1, key: 'u' }, { dx: 0, dy: 1, key: 'd' },
];

class MinHeap {
  items: { priority: number; col: number; row: number; dir: string; key: string }[] = [];
  get size() { return this.items.length; }
  push(item: typeof this.items[0]) {
    this.items.push(item);
    let i = this.items.length - 1;
    while (i > 0) {
      const p = Math.floor((i - 1) / 2);
      if (this.items[p].priority <= this.items[i].priority) break;
      [this.items[p], this.items[i]] = [this.items[i], this.items[p]]; i = p;
    }
  }
  pop() {
    if (!this.items.length) return null;
    const top = this.items[0];
    const last = this.items.pop()!;
    if (this.items.length) {
      this.items[0] = last;
      let i = 0;
      while (true) {
        const l = i * 2 + 1, r = l + 1;
        let s = i;
        if (l < this.items.length && this.items[l].priority < this.items[s].priority) s = l;
        if (r < this.items.length && this.items[r].priority < this.items[s].priority) s = r;
        if (s === i) break;
        [this.items[i], this.items[s]] = [this.items[s], this.items[i]]; i = s;
      }
    }
    return top;
  }
}

function findPath(
  grid: boolean[][], pen: number[][],
  sx: number, sy: number, ex: number, ey: number,
): { x: number; y: number }[] | null {
  const sc = nearestFree(grid, Math.max(0, Math.min(COLS - 1, Math.floor(sx / CELL))), Math.max(0, Math.min(ROWS - 1, Math.floor(sy / CELL))));
  const ec = nearestFree(grid, Math.max(0, Math.min(COLS - 1, Math.floor(ex / CELL))), Math.max(0, Math.min(ROWS - 1, Math.floor(ey / CELL))));
  if (!sc || !ec) return null;

  const open = new MinHeap();
  const cameFrom = new Map<string, string | null>();
  const cost = new Map<string, number>();
  const sk = `${sc.col},${sc.row},s`;
  open.push({ col: sc.col, row: sc.row, dir: 's', priority: 0, key: sk });
  cameFrom.set(sk, null); cost.set(sk, 0);
  let finalKey: string | null = null;

  while (open.size > 0) {
    const cur = open.pop()!;
    if (cur.col === ec.col && cur.row === ec.row) { finalKey = cur.key; break; }
    const curCost = cost.get(cur.key)!;
    for (const d of DIRS) {
      const nc = cur.col + d.dx, nr = cur.row + d.dy;
      if (isBlocked(grid, nc, nr)) continue;
      const nk = `${nc},${nr},${d.key}`;
      const turn = cur.dir !== 's' && cur.dir !== d.key ? TURN_COST : 0;
      const nc2 = curCost + 1 + turn + (pen[nr]?.[nc] ?? 0);
      if (!cost.has(nk) || nc2 < cost.get(nk)!) {
        cost.set(nk, nc2); cameFrom.set(nk, cur.key);
        open.push({ col: nc, row: nr, dir: d.key, priority: nc2 + Math.abs(nc - ec.col) + Math.abs(nr - ec.row), key: nk });
      }
    }
  }
  if (!finalKey) return null;

  const cells: { col: number; row: number }[] = [];
  let k: string | null = finalKey;
  while (k) {
    const parts = k.split(',');
    cells.push({ col: Number(parts[0]), row: Number(parts[1]) });
    k = cameFrom.get(k) ?? null;
  }
  cells.reverse();

  // simplify: keep only turn points
  const pts = cells.map(c => ({ x: (c.col + 0.5) * CELL, y: (c.row + 0.5) * CELL }));
  if (pts.length <= 2) return pts;
  const out = [pts[0]];
  let prevDir = '';
  for (let i = 1; i < pts.length; i++) {
    const dx = pts[i].x - pts[i - 1].x, dy = pts[i].y - pts[i - 1].y;
    const dir = Math.abs(dx) >= Math.abs(dy) ? (dx >= 0 ? 'r' : 'l') : (dy <= 0 ? 'u' : 'd');
    if (prevDir && dir !== prevDir) out.push(pts[i - 1]);
    prevDir = dir;
  }
  out.push(pts[pts.length - 1]);
  return out;
}

function routeLength(pts: { x: number; y: number }[]) {
  let d = 0;
  for (let i = 1; i < pts.length; i++) d += Math.abs(pts[i].x - pts[i-1].x) + Math.abs(pts[i].y - pts[i-1].y);
  return d;
}

function countTurns(pts: { x: number; y: number }[]) {
  return Math.max(0, pts.length - 2);
}

// ── Component ─────────────────────────────────────────────────────────────────
interface RouteInfo { distM: number; timeMin: number; turns: number }

export function HospitalMapViewer() {
  const { t } = useTranslation();
  const [from, setFrom] = useState<LocationKey>('entrance');
  const [to, setTo] = useState<LocationKey | ''>('');
  const [pathD, setPathD] = useState<string | null>(null);
  const [info, setInfo] = useState<RouteInfo | null>(null);
  const [animKey, setAnimKey] = useState(0);
  const [building, setBuilding] = useState(false);
  const gridRef = useRef<boolean[][] | null>(null);
  const penRef = useRef<number[][] | null>(null);

  // Build grid lazily on first use (runs in a micro-task to avoid blocking render)
  const ensureGrid = () => new Promise<void>((resolve) => {
    if (gridRef.current) { resolve(); return; }
    setBuilding(true);
    setTimeout(() => {
      gridRef.current = buildGrid();
      penRef.current = buildPenalty(gridRef.current);
      setBuilding(false);
      resolve();
    }, 10);
  });

  const handleShowRoute = async () => {
    if (!to || from === to) return;
    await ensureGrid();
    const s = LOCATIONS[from], e = LOCATIONS[to as LocationKey];
    const pts = findPath(gridRef.current!, penRef.current!, s.x, s.y, e.x, e.y);
    if (!pts || pts.length < 2) { setPathD(null); setInfo(null); return; }
    const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
    const pxDist = routeLength(pts);
    const distM = Math.round(pxDist / PX_PER_M);
    const timeMin = Math.round((distM / WALK_SPEED) * 10) / 10;
    const turns = countTurns(pts);
    setPathD(d);
    setInfo({ distM, timeMin, turns });
    setAnimKey(k => k + 1);
  };

  // Colour by location type
  const dotColor = (type: string) => {
    if (type === 'emergency') return '#e74c3c';
    if (type === 'entry') return '#27ae60';
    if (type === 'service') return '#2980b9';
    return '#8e44ad';
  };

  const locEntries = Object.entries(LOCATIONS) as [LocationKey, typeof LOCATIONS[LocationKey]][];
  const grouped = GROUP_ORDER.map(g => ({
    group: g,
    items: locEntries.filter(([, v]) => v.group === g),
  })).filter(g => g.items.length > 0);

  return (
    <div className="hmv-wrap">
      {/* Controls */}
      <div className="hmv-controls">
        <div className="hmv-from-to">
          <div className="hmv-field">
            <label className="hmv-label">{t('mapFrom', 'From')}</label>
            <select
              className="hmv-select"
              value={from}
              onChange={e => { setFrom(e.target.value as LocationKey); setPathD(null); setInfo(null); }}
            >
              {grouped.map(g => (
                <optgroup key={g.group} label={g.group}>
                  {g.items.map(([key, loc]) => (
                    <option key={key} value={key}>{t(loc.labelKey)}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>

          <div className="hmv-arrow" aria-hidden="true">→</div>

          <div className="hmv-field">
            <label className="hmv-label">{t('mapTo', 'To')}</label>
            <select
              className="hmv-select"
              value={to}
              onChange={e => { setTo(e.target.value as LocationKey); setPathD(null); setInfo(null); }}
            >
              <option value="">{t('mapSelectDepartment')}</option>
              {grouped.map(g => (
                <optgroup key={g.group} label={g.group}>
                  {g.items.map(([key, loc]) => (
                    <option key={key} value={key} disabled={key === from}>{t(loc.labelKey)}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>

          <button
            type="button"
            className="primary-btn hmv-btn"
            onClick={() => void handleShowRoute()}
            disabled={!to || to === from || building}
          >
            {building ? t('loading') : t('mapShowRoute')}
          </button>
        </div>

        {info && (
          <div className="hmv-stats">
            <span>📏 ~{info.distM} m</span>
            <span>⏱ ~{info.timeMin} min</span>
            <span>↩ {info.turns} {info.turns === 1 ? t('mapTurn', 'turn') : t('mapTurns', 'turns')}</span>
          </div>
        )}
      </div>

      {/* Map canvas */}
      <div className="hmv-canvas">
        <img
          src="/hospital-map/assets/floor-map.svg"
          alt="Hospital floor map"
          className="hmv-floor-img"
          draggable={false}
        />

        <svg
          viewBox={`0 0 ${MAP_W} ${MAP_H}`}
          preserveAspectRatio="none"
          className="hmv-overlay"
          aria-hidden="true"
        >
          {/* POI dots */}
          {locEntries.map(([key, loc]) => (
            <g key={key}>
              <circle
                cx={loc.x} cy={loc.y} r={5}
                fill={dotColor(loc.type)}
                stroke="#fff" strokeWidth={1.5}
                opacity={0.85}
              />
            </g>
          ))}

          {/* Route */}
          {pathD && (
            <g key={animKey} className="hmv-route-group">
              {/* halo */}
              <path d={pathD} stroke="rgba(0,122,255,0.25)" strokeWidth={10} fill="none" strokeLinecap="round" strokeLinejoin="round" />
              {/* main line */}
              <path
                d={pathD}
                stroke="#007AFF"
                strokeWidth={3.5}
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="hmv-route-line"
              />
            </g>
          )}

          {/* Start marker (green circle) */}
          {from && (
            <g>
              <circle cx={LOCATIONS[from].x} cy={LOCATIONS[from].y} r={9} fill="#27ae60" stroke="#fff" strokeWidth={2} />
              <text x={LOCATIONS[from].x} y={LOCATIONS[from].y + 1} textAnchor="middle" dominantBaseline="middle" fill="#fff" fontSize={8} fontWeight="bold">S</text>
            </g>
          )}

          {/* End marker (red pin) */}
          {to && to in LOCATIONS && (
            <g>
              <circle cx={LOCATIONS[to as LocationKey].x} cy={LOCATIONS[to as LocationKey].y} r={9} fill="#e74c3c" stroke="#fff" strokeWidth={2} />
              <text x={LOCATIONS[to as LocationKey].x} y={LOCATIONS[to as LocationKey].y + 1} textAnchor="middle" dominantBaseline="middle" fill="#fff" fontSize={8} fontWeight="bold">D</text>
            </g>
          )}
        </svg>

        {/* Placeholder message when no route */}
        {!pathD && (
          <div className="hmv-hint">
            {t('mapSelectPrompt')}
          </div>
        )}
      </div>
    </div>
  );
}
