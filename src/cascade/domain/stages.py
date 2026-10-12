"""The canonical shipment stage graph.

Events are timestamped milestones; a *stage* is the segment that ends at an event.
Each event therefore owns exactly one stage, which makes delay increments additive:
``delay(DELIVERED) == sum of stage increments``.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class EventType(StrEnum):
    GATE_IN_ORIGIN = "GATE_IN_ORIGIN"
    DEPART_ORIGIN = "DEPART_ORIGIN"
    ARRIVE_TS = "ARRIVE_TS"
    DEPART_TS = "DEPART_TS"
    ARRIVE_DEST_PORT = "ARRIVE_DEST_PORT"
    DISCHARGED = "DISCHARGED"
    CUSTOMS_CLEARED = "CUSTOMS_CLEARED"
    GATE_OUT = "GATE_OUT"
    DELIVERED = "DELIVERED"


ALL_EVENTS: tuple[EventType, ...] = tuple(EventType)
TS_EVENTS: frozenset[EventType] = frozenset({EventType.ARRIVE_TS, EventType.DEPART_TS})
EVENT_INDEX: dict[EventType, int] = {e: i for i, e in enumerate(ALL_EVENTS)}


class Stage(StrEnum):
    PRE_CARRIAGE = "PRE_CARRIAGE"  # shipper -> origin terminal
    ORIGIN_HANDLING = "ORIGIN_HANDLING"  # terminal -> vessel departure
    OCEAN_TO_HUB = "OCEAN_TO_HUB"
    HUB_DWELL = "HUB_DWELL"  # transshipment connection
    OCEAN_TO_DEST = "OCEAN_TO_DEST"
    BERTH_DISCHARGE = "BERTH_DISCHARGE"
    CUSTOMS = "CUSTOMS"
    PICKUP = "PICKUP"  # release -> gate-out (truck appointment / rail departure)
    INLAND = "INLAND"  # gate-out -> consignee


class StageGroup(StrEnum):
    """Coarser buckets used for explanations and the UI."""

    ORIGIN = "ORIGIN"
    OCEAN = "OCEAN"
    TRANSSHIPMENT = "TRANSSHIPMENT"
    PORT = "PORT"
    CUSTOMS = "CUSTOMS"
    INLAND = "INLAND"
    CONTEXT = "CONTEXT"
    DATA_QUALITY = "DATA_QUALITY"


STAGE_OF_EVENT: dict[EventType, Stage] = {
    EventType.GATE_IN_ORIGIN: Stage.PRE_CARRIAGE,
    EventType.DEPART_ORIGIN: Stage.ORIGIN_HANDLING,
    EventType.ARRIVE_TS: Stage.OCEAN_TO_HUB,
    EventType.DEPART_TS: Stage.HUB_DWELL,
    EventType.ARRIVE_DEST_PORT: Stage.OCEAN_TO_DEST,
    EventType.DISCHARGED: Stage.BERTH_DISCHARGE,
    EventType.CUSTOMS_CLEARED: Stage.CUSTOMS,
    EventType.GATE_OUT: Stage.PICKUP,
    EventType.DELIVERED: Stage.INLAND,
}

GROUP_OF_STAGE: dict[Stage, StageGroup] = {
    Stage.PRE_CARRIAGE: StageGroup.ORIGIN,
    Stage.ORIGIN_HANDLING: StageGroup.ORIGIN,
    Stage.OCEAN_TO_HUB: StageGroup.OCEAN,
    Stage.HUB_DWELL: StageGroup.TRANSSHIPMENT,
    Stage.OCEAN_TO_DEST: StageGroup.OCEAN,
    Stage.BERTH_DISCHARGE: StageGroup.PORT,
    Stage.CUSTOMS: StageGroup.CUSTOMS,
    Stage.PICKUP: StageGroup.INLAND,
    Stage.INLAND: StageGroup.INLAND,
}

STAGE_LABEL: dict[Stage, str] = {
    Stage.PRE_CARRIAGE: "Pre-carriage to origin terminal",
    Stage.ORIGIN_HANDLING: "Origin handling & vessel departure",
    Stage.OCEAN_TO_HUB: "Ocean leg to hub",
    Stage.HUB_DWELL: "Transshipment connection",
    Stage.OCEAN_TO_DEST: "Ocean leg to destination",
    Stage.BERTH_DISCHARGE: "Berthing & discharge",
    Stage.CUSTOMS: "Customs clearance",
    Stage.PICKUP: "Terminal pickup",
    Stage.INLAND: "Inland delivery",
}

GROUP_LABEL: dict[StageGroup, str] = {
    StageGroup.ORIGIN: "Origin",
    StageGroup.OCEAN: "Ocean transit",
    StageGroup.TRANSSHIPMENT: "Transshipment",
    StageGroup.PORT: "Destination port",
    StageGroup.CUSTOMS: "Customs",
    StageGroup.INLAND: "Inland & delivery",
    StageGroup.CONTEXT: "Route & season context",
    StageGroup.DATA_QUALITY: "Data quality",
}

# Groups that represent physical stages (can be a root cause).
PHYSICAL_GROUPS: tuple[StageGroup, ...] = (
    StageGroup.ORIGIN,
    StageGroup.OCEAN,
    StageGroup.TRANSSHIPMENT,
    StageGroup.PORT,
    StageGroup.CUSTOMS,
    StageGroup.INLAND,
)


class Checkpoint(IntEnum):
    """Index of the last observed event (0 = booked, nothing observed)."""

    BOOKED = 0
    AFTER_GATE_IN_ORIGIN = 1
    AFTER_DEPART_ORIGIN = 2
    AFTER_ARRIVE_TS = 3
    AFTER_DEPART_TS = 4
    AFTER_ARRIVE_DEST_PORT = 5
    AFTER_DISCHARGED = 6
    AFTER_CUSTOMS_CLEARED = 7
    AFTER_GATE_OUT = 8
    AFTER_DELIVERED = 9


def checkpoint_after(event: EventType | None) -> Checkpoint:
    return Checkpoint.BOOKED if event is None else Checkpoint(EVENT_INDEX[event] + 1)


CHECKPOINT_GROUP: dict[int, str] = {
    0: "pre_departure",
    1: "pre_departure",
    2: "at_sea",
    3: "at_sea",
    4: "at_sea",
    5: "at_port",
    6: "at_port",
    7: "post_customs",
    8: "post_customs",
    9: "post_customs",
}


def event_sequence(has_transshipment: bool) -> tuple[EventType, ...]:
    """Events a shipment actually passes through (direct routes skip the hub)."""
    if has_transshipment:
        return ALL_EVENTS
    return tuple(e for e in ALL_EVENTS if e not in TS_EVENTS)
