import type { Group, Tier } from "./types";

export const PORTS: Record<string, { name: string; ll: [number, number] }> = {
  CNSHA: { name: "Shanghai", ll: [121.47, 31.23] },
  CNYTN: { name: "Yantian", ll: [114.27, 22.57] },
  KRPUS: { name: "Busan", ll: [129.04, 35.1] },
  INNSA: { name: "Nhava Sheva", ll: [72.95, 18.95] },
  VNSGN: { name: "Ho Chi Minh City", ll: [106.7, 10.77] },
  SGSIN: { name: "Singapore", ll: [103.84, 1.26] },
  LKCMB: { name: "Colombo", ll: [79.84, 6.94] },
  AEJEA: { name: "Jebel Ali", ll: [55.06, 25.01] },
  MYTPP: { name: "Tanjung Pelepas", ll: [103.55, 1.36] },
  NLRTM: { name: "Rotterdam", ll: [4.14, 51.95] },
  DEHAM: { name: "Hamburg", ll: [9.97, 53.54] },
  BEANR: { name: "Antwerp", ll: [4.4, 51.26] },
  GBFXT: { name: "Felixstowe", ll: [1.33, 51.96] },
  USLAX: { name: "Los Angeles", ll: [-118.27, 33.74] },
};
export const port = (code?: string | null) => (code ? (PORTS[code]?.name ?? code) : "");

/** Plain-language stage names (no "transshipment", no "P50"). */
export const GROUP: Record<Group, string> = {
  ORIGIN: "Origin",
  OCEAN: "At sea",
  TRANSSHIPMENT: "Hub transfer",
  PORT: "Arrival port",
  CUSTOMS: "Customs",
  INLAND: "Final delivery",
};
export const groupName = (g?: string | null) => (g ? (GROUP[g as Group] ?? g) : "—");

export const EVENT: Record<string, { short: string; long: (hub?: string, dest?: string, origin?: string) => string }> = {
  GATE_IN_ORIGIN: { short: "Gate in", long: (_h, _d, o) => `Container in at ${o}` },
  DEPART_ORIGIN: { short: "Sails", long: (_h, _d, o) => `Leaves ${o}` },
  ARRIVE_TS: { short: "Hub in", long: (h) => `Reaches ${h}` },
  DEPART_TS: { short: "Hub out", long: (h) => `Leaves ${h}` },
  ARRIVE_DEST_PORT: { short: "Port in", long: (_h, d) => `Reaches ${d}` },
  DISCHARGED: { short: "Unloaded", long: () => "Unloaded" },
  CUSTOMS_CLEARED: { short: "Customs", long: () => "Customs cleared" },
  GATE_OUT: { short: "Gate out", long: () => "Leaves port" },
  DELIVERED: { short: "Delivered", long: () => "Delivered" },
};

export const CHECKPOINT: Record<string, string> = {
  BOOKED: "Booked",
  AFTER_GATE_IN_ORIGIN: "Container in",
  AFTER_DEPART_ORIGIN: "Sailed",
  AFTER_ARRIVE_TS: "Hub arrival",
  AFTER_DEPART_TS: "Left hub",
  AFTER_ARRIVE_DEST_PORT: "At port",
  AFTER_DISCHARGED: "Unloaded",
  AFTER_CUSTOMS_CLEARED: "Cleared",
  AFTER_GATE_OUT: "Out of port",
  AFTER_DELIVERED: "Delivered",
};
export const checkpointLabel = (label: string) => {
  const key = "AFTER_" + label.replace(/^After /, "").toUpperCase().replace(/ /g, "_");
  return label === "Booked" ? "Booked" : (CHECKPOINT[key] ?? label);
};

/** color = marks (dots, bars); ink = text in that status (darker in light mode for contrast). */
export const TIER: Record<Tier, { label: string; color: string; ink: string; wash: string }> = {
  ON_TRACK: { label: "On time", color: "var(--ok)", ink: "var(--ok-ink)", wash: "color-mix(in oklab, var(--ok) 14%, transparent)" },
  AT_RISK: { label: "At risk", color: "var(--risk)", ink: "var(--risk-ink)", wash: "color-mix(in oklab, var(--risk) 16%, transparent)" },
  LATE: { label: "Late", color: "var(--late)", ink: "var(--late-ink)", wash: "var(--late-wash)" },
};

/** Hours → "+10.0 days" / "+18 h" / "on time". Values that round to zero never carry a sign. */
export function delay(h: number, opts: { sign?: boolean; short?: boolean } = {}) {
  const { sign = true, short = false } = opts;
  const a = Math.abs(h);
  if (a < 0.5) return short ? "0 h" : "on time";
  const s = a >= 48 ? `${(a / 24).toFixed(1)}${short ? " d" : " days"}` : `${Math.round(a)} h`;
  return (sign ? (h > 0 ? "+" : "−") : "") + s;
}
/** Split for display: value + unit + sign, e.g. { v: "10.0", u: "days", sign: "+" }. */
export function delayParts(h: number) {
  const a = Math.abs(h);
  if (a < 0.5) return { v: "0", u: "hours", sign: "" };
  const sign = h < 0 ? "−" : "+";
  if (a >= 48) return { v: (a / 24).toFixed(1), u: "days", sign };
  return { v: String(Math.round(a)), u: "hours", sign };
}
/** Signed number with a true minus sign and no "−0" / "+0.0": signed(-0.04, 1) → "0.0". */
export function signed(x: number, digits = 0) {
  const r = Number(x.toFixed(digits));
  const body = Math.abs(r).toFixed(digits);
  return r > 0 ? `+${body}` : r < 0 ? `−${body}` : body;
}

export const pct = (x: number, digits = 0) => `${(x * 100).toFixed(digits)}%`;

export function usd(x: number, signed = false) {
  const v = Math.round(x);
  if (v === 0) return "$0";
  const s = `$${Math.abs(v).toLocaleString("en-US")}`;
  return v < 0 ? `−${s}` : signed ? `+${s}` : s;
}

// All model times are UTC (the simulator's clock). Dates are shown in UTC and labelled as such
// wherever a time of day appears, so a viewer in another zone never sees a shifted day.
const tz = { timeZone: "UTC" } as const;
export const day = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { ...tz, day: "numeric", month: "short" });
export const dayLong = (iso: string, withYear = false) =>
  new Date(iso).toLocaleDateString("en-GB", {
    ...tz,
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(withYear ? { year: "numeric" } : {}),
  });
export const dateTime = (iso: string) =>
  `${new Date(iso).toLocaleString("en-GB", { ...tz, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} UTC`;

export function ago(hours: number) {
  if (hours < 1) return "just now";
  if (hours < 24) return `${Math.round(hours)} h ago`;
  const d = Math.round(hours / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export const lanePorts = (lane: string) => lane.split("-");
export const route = (lane: string) => lanePorts(lane).map(port).join(" → ");

export const hoursBetween = (a: string, b: string) => (new Date(b).getTime() - new Date(a).getTime()) / 36e5;
