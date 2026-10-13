"""Public API v1 request models (Pydantic v2). Responses are plain dicts built by the engine."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from cascade.domain.delay import to_hours
from cascade.domain.network import CARRIER_CODES, LANES
from cascade.domain.stages import EVENT_INDEX, EventType, event_sequence
from cascade.features.snapshot import ShipmentView, WhatIf

Audience = Literal["ops", "customer", "analyst"]


class ScheduleRevisionIn(BaseModel):
    """A carrier re-plan: new planned times for some milestones, known from effective_at."""

    effective_at: AwareDatetime
    planned: dict[EventType, AwareDatetime] = Field(min_length=1)


class ShipmentIn(BaseModel):
    shipment_id: str = Field(min_length=1, max_length=64, examples=["SHP-000123"])
    lane_id: str = Field(examples=["CNSHA-SGSIN-NLRTM"])
    carrier: str = Field(examples=["C3"])
    commodity_risk: int = Field(ge=0, le=2)
    docs_complete: bool = True
    inland_mode: Literal["truck", "rail"] = "truck"
    cargo_value_usd: float = Field(default=60000.0, ge=0)
    carrier_edi_tier: int = Field(default=2, ge=1, le=3)
    planned: dict[EventType, AwareDatetime]
    observed: dict[EventType, AwareDatetime] = Field(default_factory=dict, max_length=50)
    # Optional: when each observed milestone's message reached you. A milestone only counts once
    # it has arrived by `as_of`; omitted = known from its event time.
    reported_at: dict[EventType, AwareDatetime] = Field(default_factory=dict, max_length=50)
    # Optional carrier schedule versions. `planned` stays the original commitment (lateness is
    # measured against it); revisions only inform the "current plan" shown beside the ETA.
    schedule_revisions: list[ScheduleRevisionIn] = Field(default_factory=list, max_length=50)

    @field_validator("lane_id")
    @classmethod
    def _lane(cls, v: str) -> str:
        if v not in LANES:
            raise ValueError(f"unknown lane_id '{v}'; known lanes: {sorted(LANES)}")
        return v

    @field_validator("carrier")
    @classmethod
    def _carrier(cls, v: str) -> str:
        if v not in CARRIER_CODES:
            raise ValueError(f"unknown carrier '{v}'")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> ShipmentIn:
        seq = event_sequence(LANES[self.lane_id].has_transshipment)
        missing = [e.value for e in seq if e not in self.planned]
        if missing:
            raise ValueError(f"planned timestamps missing for {missing}")
        extra = [e.value for e in self.observed if e not in seq]
        if extra:
            raise ValueError(f"observed events not on this lane's stage graph: {extra}")
        obs = sorted(self.observed.items(), key=lambda kv: EVENT_INDEX[kv[0]])
        for (e1, t1), (e2, t2) in zip(obs, obs[1:], strict=False):
            if t2 < t1:
                raise ValueError(
                    f"observed {e2.value} ({t2.isoformat()}) is earlier than {e1.value}"
                )
        for e, ra in self.reported_at.items():
            if e not in self.observed:
                raise ValueError(f"reported_at given for {e.value}, which is not observed")
            if ra < self.observed[e]:
                raise ValueError(f"reported_at for {e.value} is before the event itself")
        return self

    def to_view(self) -> ShipmentView:
        return ShipmentView(
            shipment_id=self.shipment_id,
            lane_id=self.lane_id,
            carrier=self.carrier,
            commodity_risk=self.commodity_risk,
            docs_complete=self.docs_complete,
            inland_mode=self.inland_mode,
            cargo_value_usd=self.cargo_value_usd,
            planned={e: to_hours(t) for e, t in self.planned.items()},
            reported={e: to_hours(t) for e, t in self.observed.items()},
            carrier_edi_tier=self.carrier_edi_tier,
            available={e: to_hours(t) for e, t in self.reported_at.items()},
            revisions=tuple(
                (to_hours(r.effective_at), {e: to_hours(t) for e, t in r.planned.items()})
                for r in self.schedule_revisions
            ),
        )


class Options(BaseModel):
    top_k: int = Field(default=5, ge=1, le=20)
    include_waterfall: bool = True
    audience: Audience = "ops"
    explain: bool = True


class PredictRequest(BaseModel):
    shipment: ShipmentIn
    as_of: AwareDatetime
    options: Options = Field(default_factory=Options)

    @model_validator(mode="after")
    def _not_future(self) -> PredictRequest:
        late = [e.value for e, t in self.shipment.observed.items() if t > self.as_of]
        if late:
            raise ValueError(f"observed events after as_of: {late}")
        return self


class BatchRequest(BaseModel):
    items: list[PredictRequest] = Field(min_length=1, max_length=1000)


class WhatIfIn(BaseModel):
    dest_rho: float | None = Field(default=None, ge=0.3, le=0.97)
    hub_priority: bool = False
    customs_weekend: bool | None = None
    docs_complete: bool | None = None
    inland_mode: Literal["truck", "rail"] | None = None
    delay_shift_h: float = Field(default=0.0, ge=-240, le=720)

    def to_whatif(self) -> WhatIf:
        return WhatIf(**self.model_dump())


class WhatIfRequest(PredictRequest):
    whatif: WhatIfIn


class ScenarioRequest(BaseModel):
    preset: str | None = Field(default=None, examples=["sgsin_congestion"])
    kind: Literal["congestion", "weather"] | None = None
    target: str | None = None
    delta: float | None = Field(default=None, ge=-0.5, le=0.8)
    duration_h: float = Field(default=120.0, gt=0, le=24 * 30)
    as_of: AwareDatetime | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, examples=["priya"])
    password: str = Field(min_length=1, max_length=256)
    bearer: bool = Field(False, description="Also return the token in the body, for API clients.")


class DemoLoginRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64, examples=["priya"])
    bearer: bool = Field(False, description="Also return the token in the body, for API clients.")
