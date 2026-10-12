"""Disruption scenarios for the fleet-level Impact Radar."""

from __future__ import annotations

from dataclasses import dataclass

from cascade.domain.network import PORTS, REGIONS
from cascade.sim.external import ExternalSeries


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    label: str
    kind: str  # congestion | weather
    target: str  # port code or sea region
    delta: float
    start_h: float
    duration_h: float

    def apply(self, ext: ExternalSeries) -> ExternalSeries:
        if self.kind == "congestion" and self.target not in PORTS:
            raise ValueError(f"unknown port {self.target}")
        if self.kind == "weather" and self.target not in REGIONS:
            raise ValueError(f"unknown region {self.target}")
        return ext.with_shock(
            self.kind, self.target, self.start_h, self.start_h + self.duration_h, self.delta
        )


def presets(now_h: float) -> list[Scenario]:
    return [
        Scenario(
            "sgsin_congestion",
            "Singapore congestion +15% for 5 days",
            "congestion",
            "SGSIN",
            0.15,
            now_h,
            5 * 24,
        ),
        Scenario(
            "north_sea_storm",
            "North-Europe storm for 3 days",
            "weather",
            "NORTH_EUROPE",
            0.5,
            now_h + 24,
            3 * 24,
        ),
        Scenario(
            "rtm_surge",
            "Rotterdam berth surge +12% for 10 days",
            "congestion",
            "NLRTM",
            0.12,
            now_h,
            10 * 24,
        ),
        Scenario(
            "indian_ocean_storm",
            "Indian Ocean cyclone for 4 days",
            "weather",
            "INDIAN_OCEAN",
            0.6,
            now_h,
            4 * 24,
        ),
    ]
