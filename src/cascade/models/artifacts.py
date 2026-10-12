"""Immutable, checksummed model bundles: artifacts/v{semver}/ with a manifest.

Serving refuses a bundle whose checksums do not verify or whose feature contract
(registry hash) differs from the running code, so training/serving skew cannot ship.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb

from cascade.features.registry import FEATURE_NAMES, feature_hash
from cascade.models.baselines import PropagationPrior
from cascade.models.predictor import CascadeModel

SCHEMA_VERSION = 1


class ArtifactError(RuntimeError):
    pass


TEXT_SUFFIXES = {".json", ".csv", ".txt"}


def _sha256(path: Path) -> str:
    """Content hash that ignores line endings for text files.

    Git may check text files out with CRLF (Windows, ``core.autocrlf``) or LF, so a raw-byte hash
    published on one OS would fail to verify on another. Text files are hashed with CRLF folded to
    LF; binary files (``.npz``) are hashed as stored.
    """
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or "uncommitted"
    except Exception:
        return "unknown"


@dataclass
class Bundle:
    model: CascadeModel
    manifest: dict
    path: Path


def save_bundle(model: CascadeModel, out_dir: Path, extra_manifest: dict | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "models").mkdir(exist_ok=True)
    for name, booster in model.boosters.items():
        (out_dir / "models" / f"{name}.txt").write_text(booster.model_to_string(), newline="\n")
    state = {
        "offsets": model.offsets,
        "offsets80": model.offsets80,
        "late_alert_p": model.late_alert_p,
        "drift_ref": model.drift_ref,
        "iso_x": model.iso_x,
        "iso_y": model.iso_y,
        "priors": model.priors,
        "fallback": model.fallback.to_dict(),
        "target_mode": model.target_mode,
        "late_threshold_h": model.late_threshold_h,
        "stage_weights": model.stage_weights,
        "shrink": model.shrink,
        "late_blend": model.late_blend,
        "eta_floor_frac": model.eta_floor_frac,
        "version": model.version,
        "feature_names": list(FEATURE_NAMES),
    }
    (out_dir / "model.json").write_text(json.dumps(state, indent=1), newline="\n")
    files = sorted(p for p in out_dir.rglob("*") if p.is_file() and p.name != "manifest.json")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "version": model.version,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "feature_hash": feature_hash(),
        "files": {str(p.relative_to(out_dir)).replace("\\", "/"): _sha256(p) for p in files},
        **(extra_manifest or {}),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1, default=str), newline="\n"
    )
    return out_dir


def load_bundle(path: Path, verify: bool = True) -> Bundle:
    mpath = path / "manifest.json"
    if not mpath.exists():
        raise ArtifactError(f"no manifest.json in {path}")
    manifest = json.loads(mpath.read_text())
    if verify:
        if manifest.get("feature_hash") != feature_hash():
            raise ArtifactError(
                "feature contract mismatch: bundle was trained with a different registry"
            )
        for rel, digest in manifest["files"].items():
            f = path / rel
            if not f.exists() or _sha256(f) != digest:
                raise ArtifactError(f"checksum mismatch for {rel}")
    state = json.loads((path / "model.json").read_text())
    boosters = {
        p.stem: lgb.Booster(model_str=p.read_text()) for p in (path / "models").glob("*.txt")
    }
    model = CascadeModel(
        boosters=boosters,
        offsets=state["offsets"],
        offsets80=state.get("offsets80", {}),
        late_alert_p=state.get("late_alert_p", 0.0),
        drift_ref=state.get("drift_ref", {}),
        iso_x=state["iso_x"],
        iso_y=state["iso_y"],
        priors=state["priors"],
        fallback=PropagationPrior.from_dict(state["fallback"]),
        target_mode=state["target_mode"],
        late_threshold_h=state["late_threshold_h"],
        stage_weights=state["stage_weights"],
        shrink=state["shrink"],
        late_blend=state["late_blend"],
        eta_floor_frac=state.get("eta_floor_frac", 0.5),
        version=state["version"],
    )
    return Bundle(model=model, manifest=manifest, path=path)


def latest_bundle_dir(root: Path) -> Path:
    versions = sorted(
        (p for p in root.glob("v*") if (p / "manifest.json").exists()),
        key=lambda p: tuple(int(x) for x in p.name[1:].split(".")),
    )
    if not versions:
        raise ArtifactError(f"no published bundle under {root}")
    return versions[-1]
