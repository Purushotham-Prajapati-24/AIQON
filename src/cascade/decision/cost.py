"""Cost-of-delay model (illustrative tariffs; configure with real ones in configs/costs.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Tariff:
    demurrage_free_days: float = 4.0
    demurrage_usd_per_day: tuple[float, ...] = (75.0, 150.0, 300.0)  # day bands 1-4, 5-8, 9+
    detention_usd_per_day: float = 90.0
    missed_appointment_usd: float = 350.0
    appointment_window_h: float = 24.0
    inventory_carry_pct_per_year: float = 0.20


@dataclass
class CostModel:
    default: Tariff = field(default_factory=Tariff)
    ports: dict[str, Tariff] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None) -> CostModel:
        if path is None or not path.exists():
            return cls()
        raw = yaml.safe_load(path.read_text()) or {}
        base = raw.get("default", {})
        default = Tariff(**{**Tariff().__dict__, **_tuplify(base)})
        ports = {
            k: Tariff(**{**default.__dict__, **_tuplify(v)})
            for k, v in (raw.get("ports") or {}).items()
        }
        return cls(default, ports)

    def tariff(self, port: str) -> Tariff:
        return self.ports.get(port, self.default)

    def cost(
        self,
        port: str,
        delay_h: float,
        dwell_h: float,
        inland_extra_h: float,
        cargo_value_usd: float,
    ) -> dict[str, float]:
        """Cost for one scenario of total delay / terminal dwell / inland overrun (hours)."""
        t = self.tariff(port)
        over = max(dwell_h / 24.0 - t.demurrage_free_days, 0.0)
        dem, remaining, band = 0.0, over, 0
        while remaining > 1e-9:
            days = min(remaining, 4.0) if band < len(t.demurrage_usd_per_day) - 1 else remaining
            dem += days * t.demurrage_usd_per_day[min(band, len(t.demurrage_usd_per_day) - 1)]
            remaining -= days
            band += 1
        det = max(inland_extra_h, 0.0) / 24.0 * t.detention_usd_per_day
        appt = t.missed_appointment_usd if delay_h > t.appointment_window_h else 0.0
        carry = cargo_value_usd * t.inventory_carry_pct_per_year / 365.0 * max(delay_h, 0.0) / 24.0
        return {
            "demurrage": dem,
            "detention": det,
            "missed_appointment": appt,
            "inventory_carry": carry,
            "total": dem + det + appt + carry,
        }


def _tuplify(d: dict) -> dict:
    return {k: tuple(v) if isinstance(v, list) else v for k, v in d.items()}
