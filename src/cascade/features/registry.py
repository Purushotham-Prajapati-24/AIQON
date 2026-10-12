"""Feature registry: every model input is declared here with its stage group and monotone sign.

Unregistered columns never reach a model; the registry hash is stored in the artifact
manifest so serving refuses a bundle built with a different feature contract.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from cascade.domain.stages import StageGroup as G


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: G
    family: str
    monotone: int = 0  # constraint on *remaining delay*: +1 / -1 / 0
    categorical: bool = False
    description: str = ""


FEATURES: tuple[FeatureSpec, ...] = (
    # ---- plan / context ------------------------------------------------------------
    FeatureSpec(
        "lane_code",
        G.CONTEXT,
        "plan",
        categorical=True,
        description="Lane (origin-hub-destination)",
    ),
    FeatureSpec("carrier_code", G.ORIGIN, "plan", categorical=True, description="Ocean carrier"),
    FeatureSpec("dest_code", G.PORT, "plan", categorical=True, description="Destination port"),
    FeatureSpec(
        "hub_code", G.TRANSSHIPMENT, "plan", categorical=True, description="Transshipment hub"
    ),
    FeatureSpec("has_transshipment", G.TRANSSHIPMENT, "plan"),
    FeatureSpec("inland_rail", G.INLAND, "plan", description="1 = rail, 0 = truck"),
    FeatureSpec("commodity_risk", G.CUSTOMS, "plan", monotone=1),
    FeatureSpec("docs_complete", G.CUSTOMS, "plan", monotone=-1),
    FeatureSpec(
        "inspection_prob_prior",
        G.CUSTOMS,
        "plan",
        monotone=1,
        description="Inspection probability implied by risk & documents",
    ),
    FeatureSpec("planned_transit_h", G.CONTEXT, "plan"),
    FeatureSpec(
        "planned_ts_buffer_h",
        G.TRANSSHIPMENT,
        "plan",
        monotone=-1,
        description="Designed connection slack at the hub",
    ),
    FeatureSpec(
        "headway_h", G.TRANSSHIPMENT, "plan", description="Hours to the next connecting sailing"
    ),
    # NB: no calendar-date features (week-of-year, peak flag). Seasonality reaches the model only
    # through its causal channels (congestion / weather forecasts), which extrapolates out-of-time.
    FeatureSpec("holidays_in_customs_window", G.CUSTOMS, "plan", monotone=1),
    # ---- progress ------------------------------------------------------------------
    FeatureSpec(
        "checkpoint", G.CONTEXT, "progress", description="Index of last observed milestone"
    ),
    FeatureSpec(
        "current_delay_h",
        G.CONTEXT,
        "progress",
        description="Delay at last observed milestone (carried forward)",
    ),
    FeatureSpec("delay_velocity_h_per_day", G.OCEAN, "progress"),
    FeatureSpec("frac_plan_elapsed", G.CONTEXT, "progress"),
    FeatureSpec("hours_since_last_event", G.DATA_QUALITY, "progress"),
    FeatureSpec(
        "overdue_h",
        G.OCEAN,
        "progress",
        monotone=1,
        description="Hours the next milestone is overdue",
    ),
    FeatureSpec("remaining_planned_h", G.CONTEXT, "progress"),
    # ---- propagation (stage interactions) -------------------------------------------
    FeatureSpec("projected_hub_arrival_delay_h", G.TRANSSHIPMENT, "propagation"),
    FeatureSpec(
        "ts_buffer_remaining_h",
        G.TRANSSHIPMENT,
        "propagation",
        monotone=-1,
        description="Connection buffer left after projected lateness and hub handling",
    ),
    FeatureSpec("p_miss_connection_prior", G.TRANSSHIPMENT, "propagation", monotone=1),
    FeatureSpec("projected_arrival_delay_h", G.OCEAN, "propagation"),
    FeatureSpec(
        "queue_excess_h",
        G.PORT,
        "propagation",
        monotone=1,
        description="Expected berth queue above plan (Kingman curve on forecast utilisation)",
    ),
    FeatureSpec("berth_window_miss_risk", G.PORT, "propagation", monotone=1),
    FeatureSpec("congestion_x_lateness", G.PORT, "propagation", monotone=1),
    FeatureSpec(
        "customs_calendar_shift_h",
        G.CUSTOMS,
        "propagation",
        monotone=1,
        description="Projected weekend/holiday wait vs plan",
    ),
    FeatureSpec("customs_weekend_risk", G.CUSTOMS, "propagation", monotone=1),
    FeatureSpec(
        "rail_alignment_h",
        G.INLAND,
        "propagation",
        monotone=1,
        description="Projected wait for the next block train vs plan",
    ),
    FeatureSpec(
        "remaining_absorption_h",
        G.OCEAN,
        "propagation",
        monotone=-1,
        description="Remaining speed-recovery capacity",
    ),
    # physics-informed nowcast, decomposed per stage group so attribution stays stage-specific
    FeatureSpec("proj_inc_origin_h", G.ORIGIN, "propagation", monotone=1),
    FeatureSpec("proj_inc_ocean_h", G.OCEAN, "propagation", monotone=1),
    FeatureSpec("proj_inc_hub_h", G.TRANSSHIPMENT, "propagation", monotone=1),
    FeatureSpec("proj_inc_port_h", G.PORT, "propagation", monotone=1),
    FeatureSpec("proj_inc_customs_h", G.CUSTOMS, "propagation", monotone=1),
    FeatureSpec("proj_inc_inland_h", G.INLAND, "propagation", monotone=1),
    # ---- external -------------------------------------------------------------------
    FeatureSpec("rho_origin", G.ORIGIN, "external", monotone=1),
    FeatureSpec("rho_hub_fcst", G.TRANSSHIPMENT, "external", monotone=1),
    FeatureSpec("rho_dest_fcst", G.PORT, "external", monotone=1),
    FeatureSpec("weather_fcst_remaining", G.OCEAN, "external", monotone=1),
    FeatureSpec("storm_flag", G.OCEAN, "external", monotone=1),
    # ---- out-of-fold priors -----------------------------------------------------------
    FeatureSpec("prior_lane_mean_delay", G.CONTEXT, "prior"),
    FeatureSpec("prior_carrier_origin_inc", G.ORIGIN, "prior"),
    FeatureSpec("prior_dest_port_inc", G.PORT, "prior"),
    FeatureSpec("prior_dest_customs_inc", G.CUSTOMS, "prior"),
    FeatureSpec("prior_hub_miss_rate", G.TRANSSHIPMENT, "prior"),
    # ---- data quality -----------------------------------------------------------------
    FeatureSpec("carrier_edi_tier", G.DATA_QUALITY, "quality"),
    FeatureSpec("n_missing_past", G.DATA_QUALITY, "quality"),
    FeatureSpec("completeness_ratio", G.DATA_QUALITY, "quality"),
)

FEATURE_NAMES: tuple[str, ...] = tuple(f.name for f in FEATURES)
CATEGORICAL: tuple[str, ...] = tuple(f.name for f in FEATURES if f.categorical)
PRIOR_FEATURES: tuple[str, ...] = tuple(f.name for f in FEATURES if f.family == "prior")
BY_NAME: dict[str, FeatureSpec] = {f.name: f for f in FEATURES}


def monotone_vector(names: tuple[str, ...] = FEATURE_NAMES) -> list[int]:
    return [BY_NAME[n].monotone for n in names]


def feature_hash() -> str:
    payload = "|".join(
        f"{f.name}:{f.family}:{f.group}:{f.monotone}:{int(f.categorical)}" for f in FEATURES
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
