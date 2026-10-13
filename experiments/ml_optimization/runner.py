"""Robust per-world runner (Windows process pools were dropping workers).

  python runner.py run <module> <tag> <seed> [candidate ...]   -> <cache>/<tag>/<seed>.json
  python runner.py summary <module> <tag>                       -> table over finished worlds

Drive it with e.g.  seq 101 120 | xargs -P 10 -I{} python runner.py run bakeoff2 a {} calib
"""

from __future__ import annotations

import importlib
import json
import os
import sys

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import pandas as pd  # noqa: E402

from common import CACHE  # noqa: E402


def main() -> None:
    cmd, module, tag = sys.argv[1:4]
    mod = importlib.import_module(module)
    out_dir = CACHE / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    if cmd == "run":
        seed = int(sys.argv[4])
        names = sys.argv[5:] or list(mod.CANDIDATES)
        if hasattr(mod, "c_rulebook"):
            names = ["rulebook", *[n for n in names if n != "rulebook"]]
        f = out_dir / f"{seed}.json"
        prev = json.loads(f.read_text()) if f.exists() else {"res": {}, "extra": {}}
        _, out, extra = mod.run_world((seed, names))
        prev["res"].update(out)
        prev["extra"].update(extra)
        f.write_text(json.dumps(prev))
        print(f"{seed} done", flush=True)
    else:
        res = {int(p.stem): json.loads(p.read_text())["res"] for p in out_dir.glob("*.json")}
        pd.set_option("display.width", 220, "display.max_rows", 500)
        print(f"{len(res)} worlds")
        print(mod.summarise(res).round(3).to_string())
        extra = {int(p.stem): json.loads(p.read_text())["extra"] for p in out_dir.glob("*.json")}
        sw = {s: e["stack_weights"] for s, e in extra.items() if "stack_weights" in e}
        if sw:
            print("\nconvex stack weights (mean):\n", pd.DataFrame(sw).T.mean().round(3).to_string())


if __name__ == "__main__":
    main()
