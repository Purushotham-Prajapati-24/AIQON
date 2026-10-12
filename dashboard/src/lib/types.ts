// Shapes returned by the CASCADE API (src/cascade/serving/app.py). Only fields the UI reads.

export type Tier = "ON_TRACK" | "AT_RISK" | "LATE";
export type Group = "ORIGIN" | "OCEAN" | "TRANSSHIPMENT" | "PORT" | "CUSTOMS" | "INLAND";

export interface Quantiles {
  p10: string;
  p50: string;
  p90: string;
}
export interface DelayHours {
  observed: number;
  p10: number;
  p50: number;
  p90: number;
}
export interface Cost {
  p10: number;
  p50: number;
  p90: number;
  p50_demurrage?: number;
  p50_detention?: number;
  p50_missed_appointment?: number;
  p50_inventory_carry?: number;
}

export interface World {
  now: string;
  now_h: number;
  n_shipments: number;
}

export interface FleetRow {
  shipment_id: string;
  lane_id: string;
  eta: Quantiles;
  delay_hours: DelayHours;
  p_late: number;
  risk_tier: Tier;
  checkpoint: string;
  cost_usd: Cost;
  status: string;
  origin: string;
  hub: string | null;
  dest: string;
  carrier: string;
  main_stage: Group | null;
  missing_events: string[];
}

export interface Fleet {
  as_of: string;
  active: FleetRow[];
  delivered: { shipment_id: string; total_delay_h: number }[];
}

export interface Alert {
  alert_id: string;
  shipment_id: string;
  rule: string;
  severity: "critical" | "warn" | "info";
  created_at: string;
  message: string;
  age_h: number;
}
export interface Alerts {
  as_of: string;
  n: number;
  alerts: Alert[];
}

export interface Driver {
  group: Group;
  label: string;
  contribution_h: number;
  phrase: string;
}
export interface WaterfallItem {
  label: string;
  hours: number;
  kind: "realized" | "baseline" | "forecast" | "guardrail" | "total";
}
export interface TimelineItem {
  event: string;
  planned: string;
  observed: string | null;
  projected: string | null;
}

export interface ShipmentView {
  shipment_id: string;
  lane_id: string;
  as_of: string;
  checkpoint: string;
  planned_delivery: string;
  eta: Quantiles;
  delay_hours: DelayHours;
  p_late: number;
  risk_tier: Tier;
  stage_forecast_hours: Partial<Record<Group, number>>;
  cost_usd: Cost;
  promise: { promise_date: string; reason: string; changes: number } | null;
  flags: { degraded: boolean; cold_start: boolean; missing_events: string[] };
  timing_ms: { total: number };
  narrative: string;
  drivers: Driver[];
  root_cause_group: Group | null;
  waterfall: WaterfallItem[];
  timeline: TimelineItem[];
  shipment: {
    carrier: string;
    origin: string;
    hub: string | null;
    dest: string;
    inland_mode: string;
    cargo_value_usd: number;
    docs_complete: boolean;
  };
  status: string;
  actual_total_delay_h?: number;
}

export interface Recommendation {
  action_id: string;
  label: string;
  description: string;
  hours_saved: number;
  usd_saved: number;
  action_cost_usd: number;
  net_value_usd: number;
  p_late_after: number;
  feasible_reason: string;
}

export interface Checkpoint {
  label: string;
  as_of: string;
  as_of_h: number;
}

/** One moment of a shipment: what planners see, what customers see, what to do. */
export interface Moment {
  ops: ShipmentView;
  customer: string;
  advise: Recommendation[];
}

export interface WhatIfParams {
  rho: number | null;
  hub: boolean;
  customs: boolean;
  docs: boolean;
}
export interface WhatIfResult {
  d: DelayHours;
  pl: number;
  tier: Tier;
  cost: number;
  eta: string;
  dd: number;
  dpl: number;
  dc: number;
}

export interface Preset {
  scenario_id: string;
  label: string;
  kind: string;
  target: string;
  delta: number;
  duration_h: number;
}
export interface ScenarioImpact {
  scenario: Preset;
  n_shipments: number;
  n_affected: number;
  delta_late_count: number;
  delta_expected_late: number;
  delta_cost_usd: number;
  affected: {
    shipment_id: string;
    lane_id: string;
    delta_p50_h: number;
    p_late_before: number;
    p_late_after: number;
    tier_before: Tier;
    tier_after: Tier;
    delta_cost_usd: number;
  }[];
}

export interface Insights {
  headline: Record<string, number | number[]>;
  accuracy: {
    overall: Record<string, { mae: number }>;
    by_checkpoint_mae: Record<string, Record<string, number>>;
    coverage_p10_p90: Record<string, number>;
    interval_width_h: Record<string, number>;
    n_test_shipments: number;
  };
  propagation: {
    by_event: Record<string, { phi_hat: number; phi_true: number }>;
    matrix: { lane_id: string; event: string; phi_hat: number; phi_true: number }[];
  };
  attribution: {
    accuracy: Record<string, number>;
    true_root_distribution: Record<string, number>;
  };
  decision: Record<string, number>;
  robustness: Record<string, { mae: number; mae_B1: number; coverage: number }>;
  meta: { n_shipments: number; version: string; late_rate: number };
}

export interface ModelInfo {
  version: string;
  metrics: Record<string, number>;
  gates: Record<string, { value: number; rule: string; pass: boolean }>;
}
