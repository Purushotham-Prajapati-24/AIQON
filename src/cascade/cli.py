"""`cascade` command-line interface."""

from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml

from cascade.eval.pipeline import ROOT, PipelineConfig, run
from cascade.models.train import TrainConfig
from cascade.sim.generator import SimConfig, generate

app = typer.Typer(
    add_completion=False, help="CASCADE — stage-aware shipment ETA & delay propagation"
)


def _train_cfg(path: Path) -> TrainConfig:
    if path.exists():
        return TrainConfig(**(yaml.safe_load(path.read_text()) or {}))
    return TrainConfig()


@app.command()
def generate_data(seed: int = 42, n: int = 300, out: Path = ROOT / "data") -> None:
    """Generate a synthetic dataset (shipments, events, cause ledger, external series)."""
    sim = generate(SimConfig(seed=seed, n_shipments=n))
    sim.save(out / f"seed{seed}")
    s = sim.shipments
    typer.echo(
        f"{len(s)} shipments -> {out / f'seed{seed}'} | late rate {s.is_late.mean():.1%} | "
        f"missed connections {(s.missed_connections > 0).mean():.1%}"
    )


@app.command("all")
def run_all(
    seed: int = 42,
    n: int = 300,
    version: str = "1.3.0",
    fast: bool = False,
    force: bool = False,
    train_config: Path = ROOT / "configs" / "train.yaml",
) -> None:
    """Generate -> train -> evaluate -> gate -> publish, end to end."""
    cfg = PipelineConfig(
        seed=seed,
        n_shipments=n,
        version=version,
        fast=fast,
        force=force,
        train=_train_cfg(train_config),
    )
    m = run(cfg, log=typer.echo)
    typer.echo(json.dumps(m["headline"], indent=1, default=str))


@app.command()
def seeds(seeds: str = "42,7,11,23,99", n: int = 300) -> None:
    """Stability study: headline metrics over several simulator seeds (no publishing)."""
    import numpy as np

    rows = []
    for s in [int(x) for x in seeds.split(",")]:
        cfg = PipelineConfig(
            seed=s,
            n_shipments=n,
            fast=True,
            publish=False,
            reports_dir=ROOT / "reports" / f"seed{s}",
        )
        rows.append(run(cfg, log=lambda *_: None)["headline"])
        typer.echo(
            f"seed {s}: MAE {rows[-1]['mae_cascade_h']:.1f} h, vs B1 {rows[-1]['mae_improvement_vs_B1']:.1%}"
        )
    keys = [k for k, v in rows[0].items() if isinstance(v, float)]
    summary = {
        k: {"mean": float(np.mean([r[k] for r in rows])), "sd": float(np.std([r[k] for r in rows]))}
        for k in keys
    }
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "seeds.json").write_text(
        json.dumps({"seeds": seeds, "summary": summary, "runs": rows}, indent=1, default=str)
    )
    for k, v in summary.items():
        typer.echo(f"{k:<32} {v['mean']:.3f} ± {v['sd']:.3f}")


@app.command()
def sensitivity(seed: int = 42, n: int = 300) -> None:
    """Simulator-parameter sensitivity: rerun on worlds whose mechanics differ (no publishing)."""
    from cascade.eval.sensitivity import run_sensitivity

    run_sensitivity(seed, n, ROOT / "reports", log=typer.echo)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, workers: int = 1) -> None:
    """Serve the latest published bundle with FastAPI/uvicorn."""
    import uvicorn

    uvicorn.run("cascade.serving.app:app", host=host, port=port, workers=workers, log_level="info")


if __name__ == "__main__":
    app()
