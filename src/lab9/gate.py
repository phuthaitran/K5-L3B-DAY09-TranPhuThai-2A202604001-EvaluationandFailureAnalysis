"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    from lab9.graders import GRADERS

    problems: list[str] = []
    graded = [m["id"] for m in spec["metrics"] if m["id"] in GRADERS]
    for name, rep in (("PR", pr), ("baseline", base)):
        problems += _report_problems(name, rep, graded, spec.get("pass_k", []))

    # Same trials as the baseline: no dropped, duplicated or cherry-picked (item, seed).
    pr_keys, base_keys = _keys(pr), _keys(base)
    if set(pr_keys) != set(base_keys):
        missing, extra = set(base_keys) - set(pr_keys), set(pr_keys) - set(base_keys)
        problems.append(f"(item, seed) set differs from baseline: {len(missing)} missing, {len(extra)} extra"
                        + (f", e.g. missing {sorted(missing)[0]}" if missing else ""))
    pm, bm = pr.get("manifest", {}), base.get("manifest", {})
    if list(pm.get("seeds") or []) != list(bm.get("seeds") or []):
        problems.append(f"seeds {pm.get('seeds')} differ from baseline {bm.get('seeds')}")
    if pm.get("items") != bm.get("items"):
        problems.append(f"manifest items {pm.get('items')} differ from baseline {bm.get('items')}")
    if spec.get("seeds") and list(pm.get("seeds") or []) != list(spec["seeds"]):
        problems.append(f"seeds {pm.get('seeds')} differ from the spec's {spec['seeds']}")

    # Slice membership comes from the label; PR may not move an item out of (or into) a slice.
    base_slices = {r.get("item_id"): sorted(r.get("slices") or []) for r in base.get("rows", [])}
    moved = sorted({r.get("item_id") for r in pr.get("rows", [])
                    if r.get("item_id") in base_slices and sorted(r.get("slices") or []) != base_slices[r.get("item_id")]})
    if moved:
        problems.append(f"slice tags differ from baseline for {len(moved)} item(s), e.g. {moved[0]}")

    if base_spec is not None:
        # check() already refused a different eval set (sha), so this is the SAME eval-set data:
        # renaming eval_set_version does not buy a fresh start either.
        problems += [f"RATCHET {p}" for p in ratchet_problems(spec, base_spec)]
    return problems


def _keys(rep: dict) -> list[tuple]:
    return [(r.get("item_id"), r.get("seed")) for r in rep.get("rows", [])]


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _report_problems(name: str, rep: dict, graded: list[str], k_values: list[int]) -> list[str]:
    """Checks one report is internally consistent: what its rows say is what its metrics say."""
    from lab9.eval import aggregate

    out: list[str] = []
    rows, man = rep.get("rows") or [], rep.get("manifest") or {}
    for k, v in (rep.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            out.append(f"{name} metric {k} is {v} (NaN/inf hides a broken grader)")
    if rep.get("evaluator_failures"):
        out.append(f"{name} has {len(rep['evaluator_failures'])} evaluator failure(s), "
                   f"first: {rep['evaluator_failures'][0]}")
    want = (man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        out.append(f"{name} has {len(rows)} rows, manifest says {man.get('items')} items x "
                   f"{len(man.get('seeds') or [])} seeds = {want}")
    keys = _keys(rep)
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        out.append(f"{name} has {len(dup)} duplicated (item, seed) row(s), e.g. {dup[0]}")
    if len({k[0] for k in keys}) != man.get("items"):
        out.append(f"{name} rows cover {len({k[0] for k in keys})} items, manifest says {man.get('items')}")
    bad_cells = [(r.get("item_id"), r.get("seed"), m) for r in rows for m in graded if not isinstance(r.get(m), bool)]
    if bad_cells:
        out.append(f"{name} has {len(bad_cells)} graded cell(s) that are not True/False "
                   f"(missing / crashed grader), e.g. {bad_cells[0]}")
    if any(not _finite(r.get("cost", 0.0)) for r in rows):
        out.append(f"{name} has a row with a non-finite cost")
    if rows and not bad_cells and all("cost" in r for r in rows):
        # Metrics must be what the rows say: recompute and compare (catches edited summary numbers).
        fresh = aggregate(rows, [m for m in graded if all(m in r for r in rows)], k_values=k_values)
        for k, v in (rep.get("metrics") or {}).items():
            if k in fresh and not _same_number(v, fresh[k]):
                out.append(f"{name} metric {k}={v} but its rows give {fresh[k]}")
    return out


def _same_number(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return _finite(a) and _finite(b) and abs(float(a) - float(b)) <= 1e-9


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Thresholds may only get stricter against the spec on main (same eval-set data)."""
    out: list[str] = []
    new = {m["id"]: m for m in spec.get("metrics") or []}
    for old in base_spec.get("metrics") or []:
        mid = old["id"]
        if mid not in new:
            out.append(f"metric {mid} removed")
            continue
        out += [f"metric {mid}: {p}" for p in _looser(old, new[mid], old.get("threshold") or {},
                                                        new[mid].get("threshold") or {})]
    new_sl = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for old in base_spec.get("slices") or []:
        key = (old["name"], old["metric"])
        if key not in new_sl:
            out.append(f"slice {key[0]}/{key[1]} removed")
            continue
        out += [f"slice {key[0]}/{key[1]}: {p}" for p in _looser(old, new_sl[key], old, new_sl[key])]
    if list(spec.get("seeds") or []) != list(base_spec.get("seeds") or []):
        out.append(f"seeds changed {base_spec.get('seeds')} -> {spec.get('seeds')}")
    if spec.get("eval_set") != base_spec.get("eval_set") or spec.get("labels") != base_spec.get("labels"):
        out.append("eval_set / labels path changed")
    for k in ("confidence", "n_resamples"):
        o, n = (base_spec.get("bootstrap") or {}).get(k), (spec.get("bootstrap") or {}).get(k)
        if o is not None and n != o and not (k == "n_resamples" and _finite(n) and n > o):
            out.append(f"bootstrap {k} changed {o} -> {n}")
    return out


def _looser(old: dict, new: dict, old_th: dict, new_th: dict) -> list[str]:
    out = []
    if old.get("blocking") and not new.get("blocking"):
        out.append("no longer blocking")
    if "min" in old_th and not ("min" in new_th and _finite(new_th["min"]) and new_th["min"] >= old_th["min"]):
        out.append(f"min {old_th['min']} -> {new_th.get('min')}")
    if "max" in old_th and not ("max" in new_th and _finite(new_th["max"]) and new_th["max"] <= old_th["max"]):
        out.append(f"max {old_th['max']} -> {new_th.get('max')}")
    if "max_increase" in old_th and not ("max_increase" in new_th and _finite(new_th["max_increase"])
                                         and new_th["max_increase"] <= old_th["max_increase"]):
        out.append(f"max_increase {old_th['max_increase']} -> {new_th.get('max_increase')}")
    if old_th.get("no_significant_drop") and not new_th.get("no_significant_drop"):
        out.append("no_significant_drop dropped")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, mid = s["name"], s["metric"]
        sid = f"slice:{name}/{mid}"
        a, b = per_item(pr, mid, slice_name=name), per_item(base, mid, slice_name=name)
        verdict, note = "ok", f"{len(a)} item"
        val = round(sum(a.values()) / len(a), 4) if a else None
        if val is None:
            verdict = "missing"                       # a slice with no rows cannot vouch for anything
        elif "min" in s and val < s["min"]:
            verdict = "fail"
        if s.get("no_significant_drop") and a:
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"{len(a)} item Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<38} {val!s:<8} {json.dumps(th):<36} {note:<36} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
