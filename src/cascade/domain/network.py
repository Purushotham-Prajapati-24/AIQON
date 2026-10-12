"""Reference port network, lanes and carriers (synthetic, grounded in real geography).

Parameters are plausible, not calibrated to any specific operator. Every number is a
documented assumption; see docs/Design.md §1.3 and §2.
Time zones are fixed UTC offsets (DST ignored: <= 1h effect on calendar logic).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property

from cascade.domain.delay import EPOCH, EPOCH_WEEKDAY


@dataclass(frozen=True)
class Port:
    code: str
    name: str
    lat: float
    lon: float
    tz: float  # UTC offset, hours
    base_util: float  # long-run berth utilisation rho
    region: str
    w0_h: float = 4.0  # queue scale: wait = w0 * rho / (1 - rho)
    discharge_h: float = 20.0
    customs_base_h: float = 24.0
    customs_weekend: bool = False  # customs releases on weekends?
    holidays: tuple[str, ...] = ()
    is_cn: bool = False

    @cached_property
    def holiday_days(self) -> frozenset[int]:
        return frozenset((date.fromisoformat(d) - EPOCH.date()).days for d in self.holidays)


_NL = (
    "2025-04-18",
    "2025-04-21",
    "2025-05-05",
    "2025-05-29",
    "2025-06-09",
    "2025-12-25",
    "2025-12-26",
)
_DE = (
    "2025-04-18",
    "2025-04-21",
    "2025-05-01",
    "2025-05-29",
    "2025-06-09",
    "2025-10-03",
    "2025-12-25",
    "2025-12-26",
)
_BE = (
    "2025-04-21",
    "2025-05-01",
    "2025-05-29",
    "2025-06-09",
    "2025-07-21",
    "2025-08-15",
    "2025-11-01",
    "2025-11-11",
    "2025-12-25",
)
_GB = (
    "2025-04-18",
    "2025-04-21",
    "2025-05-05",
    "2025-05-26",
    "2025-08-25",
    "2025-12-25",
    "2025-12-26",
)
_US = (
    "2025-01-01",
    "2025-01-20",
    "2025-02-17",
    "2025-05-26",
    "2025-06-19",
    "2025-07-04",
    "2025-09-01",
    "2025-10-13",
    "2025-11-11",
    "2025-11-27",
    "2025-12-25",
)

PORTS: dict[str, Port] = {
    p.code: p
    for p in [
        # origins
        Port("CNSHA", "Shanghai", 31.23, 121.47, 8, 0.72, "EAST_ASIA", is_cn=True),
        Port("CNYTN", "Yantian", 22.57, 114.27, 8, 0.70, "EAST_ASIA", is_cn=True),
        Port("KRPUS", "Busan", 35.10, 129.04, 9, 0.66, "EAST_ASIA"),
        Port("INNSA", "Nhava Sheva", 18.95, 72.95, 5.5, 0.74, "INDIAN_OCEAN"),
        Port("VNSGN", "Ho Chi Minh City", 10.77, 106.70, 7, 0.68, "SOUTHEAST_ASIA"),
        # hubs
        Port("SGSIN", "Singapore", 1.26, 103.84, 8, 0.74, "SOUTHEAST_ASIA"),
        Port("LKCMB", "Colombo", 6.94, 79.84, 5.5, 0.70, "INDIAN_OCEAN"),
        Port("AEJEA", "Jebel Ali", 25.01, 55.06, 4, 0.68, "MIDDLE_EAST"),
        Port("MYTPP", "Tanjung Pelepas", 1.36, 103.55, 8, 0.66, "SOUTHEAST_ASIA"),
        # destinations
        Port(
            "NLRTM",
            "Rotterdam",
            51.95,
            4.14,
            1,
            0.72,
            "NORTH_EUROPE",
            w0_h=4.0,
            customs_base_h=18,
            customs_weekend=True,
            holidays=_NL,
        ),
        Port(
            "DEHAM",
            "Hamburg",
            53.54,
            9.97,
            1,
            0.74,
            "NORTH_EUROPE",
            w0_h=4.5,
            customs_base_h=24,
            holidays=_DE,
        ),
        Port(
            "BEANR",
            "Antwerp",
            51.26,
            4.40,
            1,
            0.70,
            "NORTH_EUROPE",
            w0_h=4.0,
            customs_base_h=20,
            holidays=_BE,
        ),
        Port(
            "GBFXT",
            "Felixstowe",
            51.96,
            1.33,
            0,
            0.73,
            "NORTH_EUROPE",
            w0_h=5.0,
            customs_base_h=30,
            holidays=_GB,
        ),
        Port(
            "USLAX",
            "Los Angeles",
            33.74,
            -118.27,
            -8,
            0.75,
            "US_WEST",
            w0_h=5.0,
            customs_base_h=36,
            holidays=_US,
        ),
    ]
}


@dataclass(frozen=True)
class Lane:
    lane_id: str
    origin: str
    dest: str
    hub: str | None
    leg1_days: float  # origin -> hub (or -> dest when direct)
    leg1_region: str
    leg2_days: float = 0.0  # hub -> dest
    leg2_region: str = ""
    headway_h: float = 168.0  # connecting-service frequency at the hub
    inland_mode: str = "truck"
    inland_km: float = 250.0
    sailing_weekday: int = 3  # weekly origin service (Mon = 0)

    @property
    def has_transshipment(self) -> bool:
        return self.hub is not None

    @property
    def ocean_days(self) -> float:
        return self.leg1_days + self.leg2_days


def _lane(origin: str, hub: str | None, dest: str, **kw: object) -> Lane:
    lid = "-".join(p for p in (origin, hub, dest) if p)
    return Lane(lane_id=lid, origin=origin, dest=dest, hub=hub, **kw)  # type: ignore[arg-type]


LANES: dict[str, Lane] = {
    ln.lane_id: ln
    for ln in [
        _lane(
            "CNSHA",
            None,
            "NLRTM",
            leg1_days=30,
            leg1_region="INDIAN_OCEAN",
            inland_mode="rail",
            inland_km=600,
            sailing_weekday=1,
        ),
        _lane(
            "CNSHA",
            "SGSIN",
            "NLRTM",
            leg1_days=6,
            leg1_region="SOUTH_CHINA_SEA",
            leg2_days=23,
            leg2_region="INDIAN_OCEAN",
            headway_h=84,
            inland_mode="truck",
            inland_km=180,
            sailing_weekday=4,
        ),
        _lane(
            "CNYTN",
            None,
            "DEHAM",
            leg1_days=28,
            leg1_region="INDIAN_OCEAN",
            inland_mode="rail",
            inland_km=500,
            sailing_weekday=2,
        ),
        _lane(
            "KRPUS",
            None,
            "USLAX",
            leg1_days=11,
            leg1_region="NORTH_PACIFIC",
            inland_mode="truck",
            inland_km=300,
            sailing_weekday=0,
        ),
        _lane(
            "CNSHA",
            None,
            "USLAX",
            leg1_days=14,
            leg1_region="NORTH_PACIFIC",
            inland_mode="rail",
            inland_km=900,
            sailing_weekday=5,
        ),
        _lane(
            "VNSGN",
            "SGSIN",
            "BEANR",
            leg1_days=2.5,
            leg1_region="SOUTH_CHINA_SEA",
            leg2_days=23,
            leg2_region="INDIAN_OCEAN",
            headway_h=168,
            inland_mode="truck",
            inland_km=150,
            sailing_weekday=3,
        ),
        _lane(
            "INNSA",
            "AEJEA",
            "GBFXT",
            leg1_days=3,
            leg1_region="ARABIAN_SEA",
            leg2_days=18,
            leg2_region="INDIAN_OCEAN",
            headway_h=168,
            inland_mode="truck",
            inland_km=200,
            sailing_weekday=1,
        ),
        _lane(
            "INNSA",
            "LKCMB",
            "NLRTM",
            leg1_days=2.5,
            leg1_region="ARABIAN_SEA",
            leg2_days=18,
            leg2_region="INDIAN_OCEAN",
            headway_h=84,
            inland_mode="rail",
            inland_km=450,
            sailing_weekday=5,
        ),
        _lane(
            "VNSGN",
            "MYTPP",
            "DEHAM",
            leg1_days=2.5,
            leg1_region="SOUTH_CHINA_SEA",
            leg2_days=24,
            leg2_region="INDIAN_OCEAN",
            headway_h=168,
            inland_mode="truck",
            inland_km=220,
            sailing_weekday=0,
        ),
        _lane(
            "KRPUS",
            "SGSIN",
            "GBFXT",
            leg1_days=7,
            leg1_region="SOUTH_CHINA_SEA",
            leg2_days=24,
            leg2_region="INDIAN_OCEAN",
            headway_h=84,
            inland_mode="rail",
            inland_km=350,
            sailing_weekday=2,
        ),
        _lane(
            "CNYTN",
            "LKCMB",
            "BEANR",
            leg1_days=8,
            leg1_region="SOUTH_CHINA_SEA",
            leg2_days=19,
            leg2_region="INDIAN_OCEAN",
            headway_h=168,
            inland_mode="truck",
            inland_km=120,
            sailing_weekday=6,
        ),
        _lane(
            "CNSHA",
            "MYTPP",
            "NLRTM",
            leg1_days=6,
            leg1_region="SOUTH_CHINA_SEA",
            leg2_days=23,
            leg2_region="INDIAN_OCEAN",
            headway_h=168,
            inland_mode="truck",
            inland_km=260,
            sailing_weekday=3,
        ),
        _lane(
            "INNSA",
            None,
            "DEHAM",
            leg1_days=21,
            leg1_region="ARABIAN_SEA",
            inland_mode="truck",
            inland_km=300,
            sailing_weekday=4,
        ),
        _lane(
            "CNYTN",
            "AEJEA",
            "DEHAM",
            leg1_days=12,
            leg1_region="ARABIAN_SEA",
            leg2_days=16,
            leg2_region="INDIAN_OCEAN",
            headway_h=84,
            inland_mode="rail",
            inland_km=420,
            sailing_weekday=1,
        ),
    ]
}


@dataclass(frozen=True)
class Carrier:
    code: str
    name: str
    departure_scale_h: float  # LATENT reliability: Gamma scale of departure delay
    edi_tier: int  # 1 = excellent milestone feed, 3 = poor


CARRIERS: dict[str, Carrier] = {
    c.code: c
    for c in [
        Carrier("C1", "Carrier A", 2.0, 1),
        Carrier("C2", "Carrier B", 4.0, 1),
        Carrier("C3", "Carrier C", 6.0, 2),
        Carrier("C4", "Carrier D", 9.0, 2),
        Carrier("C5", "Carrier E", 13.0, 3),
    ]
}

# Fixed category orders: integer codes are stable between training and serving.
PORT_CODES: tuple[str, ...] = tuple(PORTS)
LANE_IDS: tuple[str, ...] = tuple(LANES)
CARRIER_CODES: tuple[str, ...] = tuple(CARRIERS)
HUB_CODES: tuple[str, ...] = ("NONE", "SGSIN", "LKCMB", "AEJEA", "MYTPP")
REGIONS: tuple[str, ...] = (
    "EAST_ASIA",
    "SOUTHEAST_ASIA",
    "SOUTH_CHINA_SEA",
    "NORTH_PACIFIC",
    "ARABIAN_SEA",
    "INDIAN_OCEAN",
    "MIDDLE_EAST",
    "NORTH_EUROPE",
    "US_WEST",
)

# --- operating constants (documented assumptions) -------------------------------------
HUB_HANDLING_H = 18.0  # planned handling before a connection
HUB_CUTOFF_H = 12.0  # cargo must be ready this long before connecting departure
HUB_MIN_SLACK_H = 6.0  # minimum designed connection slack (plus a voyage-specific slack)
BERTH_WINDOW_TOL_H = 12.0  # later than this -> berth window lost
RAIL_DEPART_LOCAL_H = 22.0  # daily block train
RAIL_CUTOFF_H = 4.0
RAIL_TRANSIT_H = 30.0
TRUCK_SPEED_KMH = 55.0
TRUCK_PICKUP_PLAN_H = 10.0
LAST_MILE_H = 4.0
RECEIVING_OPEN_H, RECEIVING_CLOSE_H = 8.0, 18.0  # consignee Mon-Sat
CUSTOMS_OPEN_H, CUSTOMS_CLOSE_H = 8.0, 18.0  # Mon-Fri unless customs_weekend


# --- calendar helpers ------------------------------------------------------------------
def local_parts(t: float, tz: float) -> tuple[int, int, float]:
    """(local day index since EPOCH, weekday Mon=0, local hour-of-day)."""
    local = t + tz
    day = math.floor(local / 24.0)
    return day, (day + EPOCH_WEEKDAY) % 7, local - day * 24.0


def next_open_slot(
    t: float,
    tz: float,
    open_h: float,
    close_h: float,
    open_weekdays: frozenset[int],
    holidays: frozenset[int] = frozenset(),
) -> float:
    """Earliest time >= t inside an opening window (local time)."""
    for _ in range(30):
        day, wd, hour = local_parts(t, tz)
        if wd in open_weekdays and day not in holidays:
            if hour < open_h:
                return t + (open_h - hour)
            if hour < close_h:
                return t
        t = t + (24.0 - hour) + 1e-7  # jump to next local midnight; loop re-checks the day
    return t


WEEKDAYS = frozenset(range(5))
MON_SAT = frozenset(range(6))
ALL_DAYS = frozenset(range(7))


def customs_release(t_ready: float, port: Port) -> float:
    days = ALL_DAYS if port.customs_weekend else WEEKDAYS
    hol = frozenset() if port.customs_weekend else port.holiday_days
    return next_open_slot(t_ready, port.tz, CUSTOMS_OPEN_H, CUSTOMS_CLOSE_H, days, hol)


def receiving_slot(t_arrive: float, port: Port) -> float:
    return next_open_slot(
        t_arrive, port.tz, RECEIVING_OPEN_H, RECEIVING_CLOSE_H, MON_SAT, port.holiday_days
    )


def next_rail_departure(t_ready: float, port: Port) -> float:
    """Daily block train at RAIL_DEPART_LOCAL_H; cargo must be ready RAIL_CUTOFF_H before."""
    t = t_ready + RAIL_CUTOFF_H
    day, _, hour = local_parts(t, port.tz)
    dep = (day * 24.0 + RAIL_DEPART_LOCAL_H) - port.tz
    return dep if dep >= t else dep + 24.0


def queue_wait_h(rho: float, w0: float) -> float:
    """Kingman-like congestion curve: explodes as utilisation -> 1."""
    rho = min(max(rho, 0.0), 0.97)
    return w0 * rho / (1.0 - rho)


@dataclass
class Network:
    ports: dict[str, Port] = field(default_factory=lambda: PORTS)
    lanes: dict[str, Lane] = field(default_factory=lambda: LANES)
    carriers: dict[str, Carrier] = field(default_factory=lambda: CARRIERS)


NETWORK = Network()
