"""External factor series: port congestion and sea-region weather.

Realized values drive the simulator. Models only ever see *as-of forecasts* for dates after
the prediction time: realized + horizon-scaled error, deterministic per (series, as_of day),
which mimics real forecast skill and prevents leakage of the future.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from cascade.domain.network import PORT_CODES, PORTS, REGIONS

N_DAYS = 430  # 2025-01-01 .. early 2026
LNY_DAY = 28  # Lunar New Year 2025-01-29


@dataclass
class ExternalSeries:
    congestion: np.ndarray  # realized [n_ports, N_DAYS]
    weather: np.ndarray  # realized [n_regions, N_DAYS]
    z_cong: np.ndarray  # forecast-error draws [n_ports, N_DAYS]
    z_wx: np.ndarray  # [n_regions, N_DAYS]
    cong_clim: np.ndarray  # climatology (base + known seasonality) [n_ports, N_DAYS]
    wx_clim: np.ndarray  # [n_regions, N_DAYS]
    port_index: dict[str, int] = field(
        default_factory=lambda: {p: i for i, p in enumerate(PORT_CODES)}
    )
    region_index: dict[str, int] = field(
        default_factory=lambda: {r: i for i, r in enumerate(REGIONS)}
    )

    # ---- point access ---------------------------------------------------------------
    @staticmethod
    def _day(t_hours: float) -> int:
        return int(min(max(math.floor(t_hours / 24.0), 0), N_DAYS - 1))

    def rho(self, port: str, t: float) -> float:
        return float(self.congestion[self.port_index[port], self._day(t)])

    def rho_forecast(self, port: str, t_target: float, as_of: float) -> float:
        i, d, a = self.port_index[port], self._day(t_target), self._day(as_of)
        val = float(self.congestion[i, d])
        if d <= a:
            return val
        # persistence of the current anomaly decays toward climatology; error grows with horizon
        h = d - a
        clim = float(self.cong_clim[i, d])
        anomaly = float(self.congestion[i, a] - self.cong_clim[i, a])
        skill = math.exp(-h / 21.0)
        fc = clim + skill * (val - clim) + (1 - skill) * 0.3 * anomaly
        sigma = min(0.01 + 0.003 * h, 0.05)
        return min(max(fc + sigma * float(self.z_cong[i, a]), 0.30), 0.97)

    def weather_mean(self, region: str, t0: float, t1: float) -> float:
        r = self.region_index[region]
        d0, d1 = self._day(t0), self._day(t1)
        return float(self.weather[r, d0 : max(d1, d0 + 1)].mean())

    def _wx_forecast_cumsum(self, r: int, a: int) -> np.ndarray:
        """Cumulative sum of the as-of-day-``a`` weather forecast for every target day (cached)."""
        cache = self.__dict__.setdefault("_wx_cache", {})
        key = (r, a)
        row = cache.get(key)
        if row is None:
            days = np.arange(N_DAYS)
            h = np.maximum(days - a, 0)
            skill = np.exp(-h / 4.0)  # storms are predictable only a few days ahead
            sigma = np.where(h > 0, np.minimum(0.03 + 0.01 * h, 0.10), 0.0)
            clim = self.wx_clim[r]
            fc = np.clip(
                clim + skill * (self.weather[r] - clim) + sigma * self.z_wx[r, a], 0.0, 1.0
            )
            fc = np.where(h > 0, fc, self.weather[r])  # past and today: realized
            row = np.concatenate([[0.0], np.cumsum(fc)])
            if len(cache) > 20_000:
                cache.clear()
            cache[key] = row
        return row

    def weather_forecast_mean(self, region: str, t0: float, t1: float, as_of: float) -> float:
        r = self.region_index[region]
        d0, d1, a = self._day(t0), self._day(t1), self._day(as_of)
        d1 = max(d1, d0 + 1)
        cs = self._wx_forecast_cumsum(r, a)
        return float((cs[d1] - cs[d0]) / (d1 - d0))

    # ---- scenarios ------------------------------------------------------------------
    def with_shock(
        self, kind: str, key: str, start: float, end: float, delta: float
    ) -> ExternalSeries:
        """Copy with an additive shock on [start, end) hours (used by scenarios & SCM)."""
        """An announced disruption shifts both the realized series and the expectation."""
        cong, wx = self.congestion.copy(), self.weather.copy()
        cc, wc = self.cong_clim.copy(), self.wx_clim.copy()
        d0, d1 = self._day(start), self._day(end)
        if kind == "congestion":
            i = self.port_index[key]
            cong[i, d0:d1] = np.clip(cong[i, d0:d1] + delta, 0.30, 0.97)
            cc[i, d0:d1] = np.clip(cc[i, d0:d1] + delta, 0.30, 0.97)
        else:
            r = self.region_index[key]
            wx[r, d0:d1] = np.clip(wx[r, d0:d1] + delta, 0.0, 1.0)
            wc[r, d0:d1] = np.clip(wc[r, d0:d1] + delta, 0.0, 1.0)
        return ExternalSeries(cong, wx, self.z_cong, self.z_wx, cc, wc)

    # ---- persistence ----------------------------------------------------------------
    def save(self, path: Path) -> None:
        np.savez_compressed(
            path,
            congestion=self.congestion,
            weather=self.weather,
            z_cong=self.z_cong,
            z_wx=self.z_wx,
            cong_clim=self.cong_clim,
            wx_clim=self.wx_clim,
        )

    @classmethod
    def load(cls, path: Path) -> ExternalSeries:
        z = np.load(path)
        return cls(
            z["congestion"], z["weather"], z["z_cong"], z["z_wx"], z["cong_clim"], z["wx_clim"]
        )


def _bump(days: np.ndarray, center: float, width: float) -> np.ndarray:
    return np.exp(-0.5 * ((days - center) / width) ** 2)


def generate_external(rng: np.random.Generator) -> ExternalSeries:
    days = np.arange(N_DAYS, dtype=float)
    n_p, n_r = len(PORT_CODES), len(REGIONS)
    cong = np.zeros((n_p, N_DAYS))
    cong_clim = np.zeros((n_p, N_DAYS))
    for i, code in enumerate(PORT_CODES):
        port = PORTS[code]
        seasonal = 0.07 * _bump(days, 290, 35)  # Q4 peak season (mid-October)
        seasonal += 0.04 * _bump(days, 290 + 365, 35)
        if port.is_cn:  # Lunar New Year shutdown backlog
            seasonal += 0.10 * _bump(days, LNY_DAY + 14, 8)
        if port.region in ("SOUTHEAST_ASIA", "INDIAN_OCEAN", "MIDDLE_EAST"):  # hubs: spill-over
            seasonal += 0.06 * _bump(days, LNY_DAY + 30, 10)
        if port.region == "NORTH_EUROPE":  # LNY wave arrives ~5-6 weeks later
            seasonal += 0.05 * _bump(days, LNY_DAY + 45, 10)
        ar = np.zeros(N_DAYS)
        eps = rng.normal(0, 0.022, N_DAYS)
        for d in range(1, N_DAYS):
            ar[d] = 0.92 * ar[d - 1] + eps[d]
        shocks = np.zeros(N_DAYS)
        for _ in range(rng.poisson(2.0)):  # strikes, equipment failures, surges
            s = int(rng.integers(0, N_DAYS - 20))
            shocks[s : s + int(rng.integers(5, 16))] += rng.uniform(0.06, 0.14)
        cong[i] = np.clip(port.base_util + seasonal + ar + shocks, 0.30, 0.97)
        cong_clim[i] = np.clip(port.base_util + seasonal, 0.30, 0.97)

    wx = np.zeros((n_r, N_DAYS))
    wx_clim = np.zeros((n_r, N_DAYS))
    doy = days % 365
    for r, region in enumerate(REGIONS):
        base = 0.12 + 0.02 * rng.standard_normal()
        season = np.zeros(N_DAYS)
        if region in ("INDIAN_OCEAN", "ARABIAN_SEA"):  # SW monsoon Jun-Sep
            season += 0.25 * ((doy >= 152) & (doy <= 273))
        if region in ("NORTH_PACIFIC", "SOUTH_CHINA_SEA", "EAST_ASIA"):  # typhoon season
            season += 0.12 * ((doy >= 182) & (doy <= 300))
        if region in ("NORTH_EUROPE",):  # winter storms
            season += 0.18 * ((doy <= 59) | (doy >= 305))
        storms = np.zeros(N_DAYS)
        rate = 1 / 35 + 1 / 25 * (season > 0).mean()
        for _ in range(rng.poisson(rate * N_DAYS)):
            s = int(rng.integers(0, N_DAYS - 7))
            storms[s : s + int(rng.integers(2, 7))] += rng.uniform(0.35, 0.75)
        noise = rng.normal(0, 0.04, N_DAYS)
        wx[r] = np.clip(base + season + storms + noise, 0.0, 1.0)
        wx_clim[r] = np.clip(base + season + rate * 4.5 * 0.55, 0.0, 1.0)  # expected storm load

    return ExternalSeries(
        congestion=cong,
        weather=wx,
        z_cong=rng.standard_normal((n_p, N_DAYS)),
        z_wx=rng.standard_normal((n_r, N_DAYS)),
        cong_clim=cong_clim,
        wx_clim=wx_clim,
    )
