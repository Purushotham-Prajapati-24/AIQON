import time

import numpy as np
import pytest


@pytest.mark.perf
def test_single_predict_with_explanation_p95_under_50ms(engine, world):
    sid = next(iter(world.views))
    v = world.views[sid]
    t = world.checkpoints(sid)[2]["as_of"]
    for _ in range(20):  # warm-up
        engine.predict(v, t, explain=True, with_promise=False)
    lat = []
    for _ in range(200):
        s = time.perf_counter()
        engine.predict(v, t, explain=True, with_promise=False)
        lat.append((time.perf_counter() - s) * 1000)
    assert np.percentile(lat, 95) < 50.0


@pytest.mark.perf
def test_batch_of_1000_under_one_second(engine, world):
    items = [(v, world.checkpoints(sid)[1]["as_of"]) for sid, v in world.views.items()]
    items = (items * (1000 // len(items) + 1))[:1000]
    engine.predict_many(items[:100], explain=False)  # warm-up, as the service does before /ready
    s = time.perf_counter()
    res = engine.predict_many(items, explain=False)
    assert len(res) == 1000
    assert time.perf_counter() - s < 1.0
