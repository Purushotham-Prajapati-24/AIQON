import { geoGraticule10, geoInterpolate, geoNaturalEarth1, geoPath } from "d3-geo";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";
import type { Feature, FeatureCollection } from "geojson";
// Loaded as a separate static asset (not inlined into the JS bundle) and parsed once.
import landUrl from "world-atlas/land-110m.json?url";
import { useSize } from "../hooks/useSize";
import { PORTS, TIER, delay, groupName, pct, port, route } from "../lib/format";
import type { FleetRow } from "../lib/types";

type LL = [number, number];

// Sea corridor from East Asia to North Europe, east → west (Malacca, Bab-el-Mandeb, Suez, Gibraltar).
const CORRIDOR: LL[] = [
  [97, 5.6], [88, 5.8], [80.5, 5.4], [70, 9.5], [58, 12.8], [51, 12.6], [43.4, 12.6], [41.5, 15.5],
  [38.4, 20.5], [34.5, 26.8], [32.55, 29.9], [32.3, 31.4], [26, 33.6], [16, 35.5], [10.5, 37.5],
  [1, 37.2], [-5.6, 35.95], [-9.8, 37.2], [-9.6, 43.2], [-5.5, 48.4], [-1.5, 50.0], [1.6, 51.0],
];
const HORMUZ: LL[] = [[56.4, 26.6], [57.6, 24.3], [60, 21.5], [57, 16.5]];
const WEST_INDIA: LL[] = [[70.5, 16.5], [62, 13.5]];

/** A plausible sea track between two ports (used for drawing only). */
function seaTrack(a: LL, b: LL, aCode: string): LL[] {
  const toEurope = b[0] < 15 && b[0] > -30 && a[0] > 40;
  if (!toEurope) return [a, b];
  let start = CORRIDOR.filter((p) => p[0] < a[0] - 1);
  let lead: LL[] = [];
  if (aCode === "AEJEA") {
    lead = HORMUZ;
    start = CORRIDOR.filter((p) => p[0] < 52);
  } else if (aCode === "INNSA") {
    lead = WEST_INDIA;
    start = CORRIDOR.filter((p) => p[0] < 58);
  }
  const tail = start.filter((p) => !(b[1] > 52 && p[0] > 1.5 && p[1] > 50)); // Hamburg goes on up the North Sea
  return [a, ...lead, ...tail, ...(b[0] > 6 ? ([[4.2, 53.2]] as LL[]) : []), b];
}

function laneTrack(lane: string): LL[] {
  // Unknown port codes (a newer API than this UI) are skipped instead of crashing the map.
  const codes = lane.split("-").filter((c) => PORTS[c]);
  const out: LL[] = [];
  if (codes.length < 2) return codes.length ? [PORTS[codes[0]].ll, PORTS[codes[0]].ll] : [[0, 0], [0, 0]];
  for (let k = 0; k < codes.length - 1; k++) {
    const seg = seaTrack(PORTS[codes[k]].ll, PORTS[codes[k + 1]].ll, codes[k]);
    out.push(...(k === 0 ? seg : seg.slice(1)));
  }
  return out;
}

/** Fraction of the voyage done at a checkpoint (rough, for placing the dot). */
function progress(checkpoint: string, hasHub: boolean) {
  const hub = 0.42;
  const m: Record<string, number> = {
    BOOKED: 0, AFTER_GATE_IN_ORIGIN: 0.01, AFTER_DEPART_ORIGIN: hasHub ? hub / 2 : 0.5,
    AFTER_ARRIVE_TS: hub, AFTER_DEPART_TS: (hub + 1) / 2,
  };
  return m[checkpoint] ?? 1;
}

// Label offsets for crowded ports: [dx, dy, anchor].
const LABEL: Record<string, [number, number, "start" | "middle" | "end"]> = {
  GBFXT: [-7, -5, "end"],
  NLRTM: [7, 1, "start"],
  BEANR: [0, 16, "middle"],
  DEHAM: [6, -8, "start"],
  SGSIN: [8, 4, "start"],
  MYTPP: [-6, 15, "end"],
  CNYTN: [8, 4, "start"],
  CNSHA: [-8, -4, "end"],
  KRPUS: [8, -6, "start"],
  VNSGN: [8, -7, "start"],
  LKCMB: [-7, 14, "end"],
  INNSA: [-7, 4, "end"],
};

type Land = Feature | FeatureCollection;
let landPromise: Promise<Land> | null = null;
function loadLand(): Promise<Land> {
  landPromise ??= fetch(landUrl)
    .then((r) => r.json() as Promise<Topology>)
    .then((topo) => feature(topo, topo.objects.land) as Land);
  return landPromise;
}

/** Status marker: shape AND colour, so risk never depends on colour vision alone. */
function Marker({ tier, r }: { tier: FleetRow["risk_tier"]; r: number }) {
  const fill = TIER[tier].color;
  if (tier === "LATE") return <rect x={-r} y={-r} width={2 * r} height={2 * r} fill={fill} stroke="var(--bg)" strokeWidth={1.5} />;
  if (tier === "AT_RISK") {
    const h = r * 1.25;
    return <path d={`M0 ${-h} L${h} ${h * 0.8} L${-h} ${h * 0.8} Z`} fill={fill} stroke="var(--bg)" strokeWidth={1.5} strokeLinejoin="round" />;
  }
  return <circle r={r} fill={fill} stroke="var(--bg)" strokeWidth={1.5} />;
}

export function FleetMap({ rows, selected, onSelect }: { rows: FleetRow[]; selected: string; onSelect: (sid: string, el: Element) => void }) {
  const [ref, { width }] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<FleetRow | null>(null);
  const [land, setLand] = useState<Land | null>(null);
  useEffect(() => {
    let alive = true;
    loadLand().then((l) => alive && setLand(l), () => undefined); // the map still works without coastlines
    return () => {
      alive = false;
    };
  }, []);
  const W = Math.max(width, 320);
  const H = Math.round(W * 0.5);

  const geo = useMemo(() => {
    const projection = geoNaturalEarth1()
      .rotate([-112, 0])
      .fitExtent([[8, 8], [W - 8, H - 8]], {
        type: "MultiPoint",
        coordinates: [[-14, 58], [244, 58], [-14, -4], [244, -4], [60, -8]],
      });
    const path = geoPath(projection);
    // Sample each lane densely so long legs follow the globe's curve.
    const tracks = new Map<string, LL[]>();
    for (const r of rows) {
      if (tracks.has(r.lane_id)) continue;
      const pts = laneTrack(r.lane_id);
      const dense: LL[] = [];
      for (let k = 0; k < pts.length - 1; k++) {
        const f = geoInterpolate(pts[k], pts[k + 1]);
        const n = Math.max(2, Math.ceil(Math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]) / 3));
        for (let s = 0; s < n; s++) dense.push(f(s / n) as LL);
      }
      dense.push(pts[pts.length - 1]);
      tracks.set(r.lane_id, dense.map((p) => projection(p) as LL));
    }
    return { projection, path, tracks };
  }, [W, H, rows]);

  const lanes = useMemo(() => {
    const by = new Map<string, FleetRow[]>();
    rows.forEach((r) => by.set(r.lane_id, [...(by.get(r.lane_id) ?? []), r]));
    return [...by.entries()].map(([lane, rs]) => ({
      lane,
      n: rs.length,
      risk: rs.reduce((a, r) => a + r.p_late, 0) / rs.length,
      d: "M" + (geo.tracks.get(lane) ?? []).map((p) => p.join(",")).join("L"),
    }));
  }, [rows, geo]);

  const dots = useMemo(() => {
    const seen = new Map<string, number>();
    return rows.map((r) => {
      const t = geo.tracks.get(r.lane_id) ?? [[0, 0] as LL];
      const f = progress(r.checkpoint, !!r.hub);
      const pos = along(t, f);
      const key = `${r.lane_id}:${f}`;
      const k = seen.get(key) ?? 0;
      seen.set(key, k + 1);
      // fan out shipments at the same spot
      const ang = k * 2.4;
      const rad = k ? 5 + k * 1.6 : 0;
      return { r, x: pos[0] + Math.cos(ang) * rad, y: pos[1] + Math.sin(ang) * rad };
    });
  }, [rows, geo]);

  const ports = useMemo(() => {
    const used = new Set(rows.flatMap((r) => r.lane_id.split("-")).filter((c) => PORTS[c]));
    return [...used].map((c) => {
      const [x, y] = geo.projection(PORTS[c].ll) as LL;
      const hub = rows.some((r) => r.hub === c);
      return { c, x, y, hub };
    });
  }, [rows, geo]);

  const color = (p: number) => (p > 0.6 ? "var(--late)" : p > 0.3 ? "var(--risk)" : "var(--ok)");
  const hd = hover ? dots.find((d) => d.r.shipment_id === hover.shipment_id) : null;

  return (
    <div ref={ref} className="relative aspect-[2/1] w-full">
      <svg
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        className="block"
        role="img"
        aria-label={`Map of ${rows.length} active shipments by lane. Late shipments are squares, at-risk triangles, on-time circles. The list below has the same shipments.`}
      >
        <path d={geo.path(geoGraticule10()) ?? ""} fill="none" stroke="var(--line)" strokeWidth={0.6} />
        {land && <path d={geo.path(land) ?? ""} fill="var(--bg-3)" stroke="var(--line-2)" strokeWidth={0.5} />}
        {lanes.map((l) => (
          <g key={l.lane}>
            <path d={l.d} fill="none" stroke={color(l.risk)} strokeOpacity={0.22} strokeWidth={1 + l.n * 0.9} strokeLinecap="round" strokeLinejoin="round" />
            <path
              d={l.d}
              fill="none"
              stroke={color(l.risk)}
              strokeWidth={1.4}
              strokeDasharray="2 10"
              strokeLinecap="round"
              style={{ animation: `dash-flow ${1.6 + (1 - l.risk) * 1.6}s linear infinite` }}
            />
          </g>
        ))}
        {ports.map((p) => (
          <g key={p.c} transform={`translate(${p.x},${p.y})`}>
            {p.hub ? (
              <rect x={-4} y={-4} width={8} height={8} transform="rotate(45)" fill="var(--bg)" stroke="var(--fg-2)" strokeWidth={1.4} />
            ) : (
              <circle r={3.2} fill="var(--fg-2)" />
            )}
            {W > 700 && (
              <text
                x={LABEL[p.c]?.[0] ?? 0}
                y={LABEL[p.c]?.[1] ?? -9}
                textAnchor={LABEL[p.c]?.[2] ?? "middle"}
                className="fill-fg-3 text-[10.5px]"
                style={{ paintOrder: "stroke", stroke: "var(--bg)", strokeWidth: 3 }}
              >
                {port(p.c)}
              </text>
            )}
          </g>
        ))}
        {dots.map(({ r, x, y }) => {
          const sel = r.shipment_id === selected;
          return (
            <g
              key={r.shipment_id}
              transform={`translate(${x},${y})`}
              className="cursor-pointer"
              onPointerEnter={() => setHover(r)}
              onPointerLeave={() => setHover(null)}
              onClick={(e) => onSelect(r.shipment_id, e.currentTarget)}
            >
              <circle r={11} fill="transparent" />
              {sel && <circle r={10} fill="none" stroke="var(--fg)" strokeWidth={1.4} />}
              <Marker tier={r.risk_tier} r={sel ? 5.5 : 4.4} />
            </g>
          );
        })}
      </svg>
      <AnimatePresence>
        {hover && hd && (
          <motion.div
            key={hover.shipment_id}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="pointer-events-none absolute z-10 w-64 rounded-md border border-line-2 bg-bg-2 p-3.5 text-sm shadow-[0_18px_40px_-20px_rgb(0_0_0/0.6)]"
            style={{ left: Math.min(Math.max(hd.x - 128, 4), W - 260), top: hd.y + 14 > H - 120 ? hd.y - 130 : hd.y + 14 }}
          >
            <div className="flex items-center justify-between font-mono text-[12px]">
              <span>{hover.shipment_id}</span>
              <span style={{ color: TIER[hover.risk_tier].ink }}>{TIER[hover.risk_tier].label}</span>
            </div>
            <div className="mt-1 text-fg-2">{route(hover.lane_id)}</div>
            <div className="mt-2 flex gap-4 font-mono text-[12px]">
              <span>{delay(hover.delay_hours.p50)}</span>
              <span className="text-fg-3">{pct(hover.p_late)} chance late</span>
            </div>
            <div className="mt-1 text-[12px] text-fg-3">Main risk ahead: {groupName(hover.main_stage)}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function along(pts: LL[], f: number): LL {
  if (f <= 0) return pts[0];
  if (f >= 1) return pts[pts.length - 1];
  const seg = pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]));
  let target = seg.reduce((a, b) => a + b, 0) * f;
  for (let i = 0; i < seg.length; i++) {
    if (target <= seg[i]) {
      const t = target / seg[i];
      return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t];
    }
    target -= seg[i];
  }
  return pts[pts.length - 1];
}
