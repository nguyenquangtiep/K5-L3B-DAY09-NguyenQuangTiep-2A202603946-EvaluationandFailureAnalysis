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
from lab9.graders import GRADERS


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
    problems: list[str] = []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]

    # 1. Metric values must be real numbers (or None for "undefined", e.g. pass_hat_k with < k runs).
    for name, rep in (("PR", pr), ("baseline", base)):
        for k, v in (rep.get("metrics") or {}).items():
            if not _finite_or_none(v):
                problems.append(f"{name} metric {k} = {v!r} is not a finite number")

    # 2. Row count and (item, seed) coverage: no dropped, duplicated or cherry-picked rows.
    man = pr.get("manifest") or {}
    rows, base_rows = pr.get("rows") or [], base.get("rows") or []
    seeds = man.get("seeds") or []
    want_n = (man.get("items") or 0) * len(seeds)
    if len(rows) != want_n:
        problems.append(f"PR has {len(rows)} rows, manifest says {man.get('items')} items x {len(seeds)} seeds = {want_n}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    base_keys = [(r.get("item_id"), r.get("seed")) for r in base_rows]
    dup = len(keys) - len(set(keys))
    if dup:
        problems.append(f"PR has {dup} duplicated (item, seed) row(s)")
    if len(base_keys) != len(set(base_keys)):
        problems.append("baseline has duplicated (item, seed) rows")
    if set(keys) != set(base_keys):
        miss, extra = set(base_keys) - set(keys), set(keys) - set(base_keys)
        problems.append(f"PR (item, seed) set differs from baseline: {len(miss)} missing, {len(extra)} extra")
    if {s for _, s in keys} != set(seeds):
        problems.append(f"PR row seeds {sorted({s for _, s in keys})} differ from manifest seeds {sorted(seeds)}")
    if len({i for i, _ in keys}) != man.get("items"):
        problems.append(f"PR rows cover {len({i for i, _ in keys})} items, manifest says {man.get('items')}")
    bman = base.get("manifest") or {}
    if (bman.get("items"), sorted(bman.get("seeds") or [])) != (man.get("items"), sorted(seeds)):
        problems.append("PR manifest items/seeds differ from the baseline's")

    # 3. Crashed graders: reported failures, or a graded metric missing / None / non-bool on a row.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), first: {pr['evaluator_failures'][0]}")
    bad_cells = [(r.get("item_id"), r.get("seed"), m) for r in rows for m in graded
                 if not isinstance(r.get(m), bool)]
    if bad_cells:
        i, s, m = bad_cells[0]
        problems.append(f"{len(bad_cells)} graded cell(s) missing/None/non-bool, first {i}@{s} {m}={rows_get(rows, i, s, m)!r}")

    # 4. Reported metrics must be what the rows say (hand-edited / recomputed-on-a-subset numbers).
    for m in graded:
        vals = [r[m] for r in rows if isinstance(r.get(m), bool)]
        if not vals or m not in (pr.get("metrics") or {}) or not _finite(pr["metrics"][m]):
            continue
        want = sum(vals) if m in COUNT_METRICS else round(sum(vals) / len(vals), 4)
        if abs(pr["metrics"][m] - want) > 1e-6:
            problems.append(f"metric {m} = {pr['metrics'][m]} but its rows give {want}")

    # 5. Slice tags are derived from labels: the same item must carry the same tags in PR and baseline.
    tags = lambda rs: {r.get("item_id"): tuple(sorted(r.get("slices") or [])) for r in rs}
    pt, bt = tags(rows), tags(base_rows)
    moved = sorted(i for i in pt.keys() & bt.keys() if pt[i] != bt[i])
    if moved:
        problems.append(f"slice tags differ from baseline on {len(moved)} item(s), first {moved[0]}: {bt[moved[0]]} -> {pt[moved[0]]}")
    per_row: dict = {}
    for r in rows:
        per_row.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
    split = sorted(i for i, t in per_row.items() if len(t) > 1)
    if split:
        problems.append(f"item {split[0]} carries different slice tags on different seeds")

    # 6. Ratchet: on the same eval set, thresholds may only get stricter. "Same eval set" means the
    #    same eval_set_sha too, so bumping the version string alone does not reset the ratchet.
    if base_spec is not None:
        same_set = (spec.get("eval_set_version") == base_spec.get("eval_set_version")
                    or man.get("eval_set_sha") == bman.get("eval_set_sha"))
        if same_set:
            problems += ratchet(spec, base_spec)
    return problems


COUNT_METRICS = {"secret_leak", "approval_bypass"}   # aggregated as counts in lab9.eval.aggregate


def rows_get(rows: list[dict], item, seed, metric: str):
    return next((r.get(metric) for r in rows if r.get("item_id") == item and r.get("seed") == seed), None)


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _finite_or_none(v) -> bool:
    return v is None or isinstance(v, bool) or _finite(v)


def _looser(new: dict, old: dict, what: str) -> list[str]:
    """Threshold `new` vs `old` for one metric (thresholds under "threshold") or one slice
    (thresholds inline); each loosening is one problem."""
    out = []
    nt = new.get("threshold", new) if "threshold" in old or "threshold" in new else new
    ot = old.get("threshold", old)
    for k in ("max", "max_increase"):
        if k in ot and (k not in nt or not _finite(nt[k]) or nt[k] > ot[k]):
            out.append(f"RATCHET {what}: {k} {ot[k]} -> {nt.get(k)}")
    if "min" in ot and ("min" not in nt or not _finite(nt["min"]) or nt["min"] < ot["min"]):
        out.append(f"RATCHET {what}: min {ot['min']} -> {nt.get('min')}")
    if ot.get("no_significant_drop") and not nt.get("no_significant_drop"):
        out.append(f"RATCHET {what}: no_significant_drop dropped")
    if old.get("blocking") and not new.get("blocking"):
        out.append(f"RATCHET {what}: blocking -> non-blocking")
    if old.get("kind") and new.get("kind") != old.get("kind"):
        out.append(f"RATCHET {what}: kind {old.get('kind')} -> {new.get('kind')}")
    return out


def ratchet(spec: dict, base_spec: dict) -> list[str]:
    out = []
    new_m = {m["id"]: m for m in spec.get("metrics", [])}
    for m in base_spec.get("metrics", []):
        if m["id"] not in new_m:
            out.append(f"RATCHET metric {m['id']} removed")
        else:
            out += _looser(new_m[m["id"]], m, f"metric {m['id']}")
    key = lambda s: (s.get("name"), s.get("metric"))
    new_s = {key(s): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        if key(s) not in new_s:
            out.append(f"RATCHET slice {s.get('name')}/{s.get('metric')} removed")
        else:
            out += _looser(new_s[key(s)], s, f"slice {s.get('name')}/{s.get('metric')}")
    if sorted(spec.get("seeds") or []) != sorted(base_spec.get("seeds") or []):
        out.append(f"RATCHET seeds {base_spec.get('seeds')} -> {spec.get('seeds')}")
    if not set(base_spec.get("pass_k") or []) <= set(spec.get("pass_k") or []):
        out.append(f"RATCHET pass_k {base_spec.get('pass_k')} -> {spec.get('pass_k')}")
    nb, ob = spec.get("bootstrap") or {}, base_spec.get("bootstrap") or {}
    if nb.get("confidence", 0.95) < ob.get("confidence", 0.95):
        out.append(f"RATCHET bootstrap confidence {ob.get('confidence')} -> {nb.get('confidence')}")
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
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"            # a slice with no rows cannot vouch for anything
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if "max" in sl and val > sl["max"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if sl.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}  ({len(a)} items)")
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
