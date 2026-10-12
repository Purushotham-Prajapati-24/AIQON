"""Shared fixtures: a small simulated world, a quickly trained model, an engine and a bundle."""

from __future__ import annotations

from pathlib import Path

import pytest

from cascade.data.splits import make_splits
from cascade.decision.cost import CostModel
from cascade.decision.engine import Engine, World
from cascade.features.dataset import build_rows
from cascade.models.artifacts import Bundle, save_bundle
from cascade.models.train import TrainConfig, train
from cascade.sim.generator import SimConfig, generate

FAST = TrainConfig(n_estimators=60, learning_rate=0.1)


@pytest.fixture(scope="session")
def sim():
    return generate(SimConfig(seed=3, n_shipments=120))


@pytest.fixture(scope="session")
def rows(sim):
    return build_rows(sim.shipments, sim.events, sim.ledger, sim.external, seed=3)


@pytest.fixture(scope="session")
def splits(sim):
    return make_splits(sim.shipments, seed=3)


@pytest.fixture(scope="session")
def trained(rows, sim, splits):
    return train(rows, sim.shipments, sim.ledger, splits, FAST, version="0.0.1")


@pytest.fixture(scope="session")
def world(sim, splits):
    s = sim.shipments[sim.shipments.shipment_id.isin(splits.test_ids)]
    e = sim.events[sim.events.shipment_id.isin(splits.test_ids)]
    return World.from_frames(s, e)


@pytest.fixture(scope="session")
def engine(trained, sim, world):
    return Engine(Bundle(trained.model, {}, Path(".")), sim.external, CostModel(), world)


@pytest.fixture(scope="session")
def bundle_dir(tmp_path_factory, trained, sim, world) -> Path:
    root = tmp_path_factory.mktemp("artifacts")
    out = root / "v0.0.1"
    out.mkdir()
    sim.external.save(out / "external.npz")
    world.save(out)
    (out / "insights.json").write_text("{}")
    save_bundle(trained.model, out, {"metrics": {}, "gates": {}})
    return root
