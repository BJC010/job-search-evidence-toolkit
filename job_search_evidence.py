"""Offline job-search evidence checkpoints and yield measurement.

Collectors supply search-page evidence; this module validates structure, not truth.
It does not access job boards, resumes, trackers, or email.
"""
import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE / "config" / "search.example.json"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize(value):
    value = unicodedata.normalize("NFKC", value).casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


def pair(role):
    result = (normalize(role["company"]), normalize(role["title"]))
    if not all(result):
        raise ValueError("Every card/tracker/role requires company and title")
    return result


def fingerprint(config):
    # Include all query/filter/priority policy, never daily evidence or timestamps.
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def plan(run_date, round_number=1, config=None):
    config = config or read(DEFAULT_CONFIG)
    day = date.fromisoformat(run_date)
    if day.weekday() > 4:
        raise ValueError("Discovery requires a weekday")
    if round_number not in (1, 2) or round_number > config["rounds"]["maximum"]:
        raise ValueError("Round is outside the configured maximum")
    cells = []
    sources = ["LinkedIn", "Indeed"] if round_number == 1 else config["source_order"]
    for source in sources:
        settings = config["sources"][source]
        windows = settings["monday_days" if day.weekday() == 0 else "other_weekday_days"]
        windows = windows[:1] if round_number == 1 else windows
        if round_number == 1:
            queries_by_lane = config["core_queries"]
        elif source == "Eluta":
            queries_by_lane = config["core_queries"]
        else:
            queries_by_lane = config["fallback_queries"]
        for lane, queries in queries_by_lane.items():
            for query in queries:
                for days in windows:
                    key = [round_number, source, lane, query, days]
                    cells.append({"cell_id": hashlib.sha256(json.dumps(key).encode()).hexdigest()[:20],
                                  "round": round_number, "source": source, "lane": lane,
                                  "query": query, "days": days, "radius_km": settings["radius_km"],
                                  "sort": settings["sort"], "page_depth": settings["pages_per_lane"]})
    if round_number == 2:
        cells = plan(run_date, 1, config)["cells"] + cells
    return {"run_date": run_date, "round": round_number, "config_fingerprint": fingerprint(config),
            "cells": cells}


def collection(raw, manifest):
    """Resolve every query through full pagination, exhausted evidence, or a blocker."""
    cards = raw.get("candidate_cards", [])
    ledger = raw.get("coverage", [])
    problems, unresolved, blocked, missing_pages, page_cap_reached = [], [], [], [], set()
    known = {c["cell_id"] for c in manifest["cells"]}
    if any(row.get("cell_id") not in known for row in ledger + cards):
        raise ValueError("Evidence includes an unknown manifest cell")
    pool = {}
    for cell in manifest["cells"]:
        rows = sorted([r for r in ledger if r["cell_id"] == cell["cell_id"]], key=lambda r: r["page"])
        terminal = False
        valid_pages = 0
        for index, row in enumerate(rows, 1):
            if terminal or row["page"] != index or index > cell["page_depth"]:
                problems.append(f"{cell['cell_id']}: invalid pagination")
                break
            required = {"filtered_results_url", "timestamp", "status", "card_count", "has_next_page", "evidence"}
            if not required <= row.keys() or not row["evidence"] or not row["timestamp"] or not row["filtered_results_url"]:
                problems.append(f"{cell['cell_id']}: missing live page evidence")
                break
            if any(row.get(k) != cell[k] for k in ("source", "lane", "query", "days", "radius_km", "sort")):
                problems.append(f"{cell['cell_id']}: filters/query differ from manifest")
                break
            page_cards = [c for c in cards if c["cell_id"] == cell["cell_id"] and c["page"] == index]
            if row["card_count"] != len({pair(c) for c in page_cards}):
                problems.append(f"{cell['cell_id']}: card count differs from saved cards")
                break
            if row["status"] == "blocked":
                if not row.get("blocker"):
                    problems.append(f"{cell['cell_id']}: blocker lacks observed reason")
                    break
                blocked.append(cell["cell_id"])
                terminal = True
            elif row["status"] in ("searched", "exhausted"):
                if row.get("page_end_observed") is not True:
                    problems.append(f"{cell['cell_id']}: results-list end not observed")
                    break
                if cell["source"] == "LinkedIn" and row.get("sort_control_observed") is not True:
                    problems.append(f"{cell['cell_id']}: LinkedIn Most recent sort not observed")
                    break
                if type(row["has_next_page"]) is not bool or (not page_cards and not row.get("no_results_evidence")):
                    problems.append(f"{cell['cell_id']}: empty/loading page is not exhaustion")
                    break
                if row["status"] == "exhausted" and row["has_next_page"]:
                    problems.append(f"{cell['cell_id']}: exhausted page still has next page")
                    break
                if index == cell["page_depth"] and row["has_next_page"]:
                    page_cap_reached.add(cell["cell_id"])
                terminal = not row["has_next_page"] or index == cell["page_depth"]
            else:
                problems.append(f"{cell['cell_id']}: invalid status")
                break
            for card in page_cards:
                if not card.get("url") or not card.get("captured_at"):
                    raise ValueError("Cards require URL and actual capture timestamp")
                pool.setdefault(pair(card), card)
            valid_pages = index
        if not terminal or any(p.startswith(cell["cell_id"]) for p in problems):
            unresolved.append(cell["cell_id"])
            missing_pages.extend({"cell_id": cell["cell_id"], "source": cell["source"],
                                  "lane": cell["lane"], "query": cell["query"], "page": p}
                                 for p in range(valid_pages + 1, cell["page_depth"] + 1))
    # Orphan pages must never enter the saved pool.
    if any(not any(r["cell_id"] == c["cell_id"] and r["page"] == c["page"] for r in ledger) for c in cards):
        raise ValueError("Card has no persisted page ledger")
    return {"candidate_pool": list(pool.values()), "required_queries": len(known),
            "resolved_queries": len(known) - len(set(unresolved)), "blocked_cells": blocked,
            "page_cap_reached_cells": sorted(page_cap_reached),
            "missing_or_invalid_cells": sorted(set(unresolved)), "problems": problems,
            "missing_or_invalid_page_cells": missing_pages,
            "collection_resolved": not unresolved,
            "coverage_status": "complete" if not unresolved and not blocked else "incomplete_coverage"}


def checkpoint(raw, manifest, config=None):
    config = config or read(DEFAULT_CONFIG)
    if manifest != plan(manifest["run_date"], manifest["round"], config):
        raise ValueError("Manifest differs from the full configured matrix")
    result = collection(raw, manifest)
    result.update({"run_date": manifest["run_date"], "manifest": manifest,
                   "coverage": raw.get("coverage", []), "candidate_cards": raw.get("candidate_cards", []),
                   "persisted_at": datetime.now(timezone.utc).isoformat()})
    return result


def measure(check, analysis, config=None):
    config = config or read(DEFAULT_CONFIG)
    if check["manifest"]["config_fingerprint"] != fingerprint(config):
        raise ValueError("Config changed since collection; regenerate the manifest")
    expected = plan(check["run_date"], check["manifest"]["round"], config)
    if check["manifest"] != expected:
        raise ValueError("Manifest differs from the full configured matrix")
    verified = collection(check, check["manifest"])
    if not verified["collection_resolved"] and analysis.get("roles"):
        raise ValueError("Scoring barrier: persist every required query/page or observed blocker first")
    tracker = analysis.get("tracker_snapshot", {})
    if not tracker.get("read_at") or tracker.get("complete") is not True or "rows" not in tracker:
        raise ValueError("Scoring requires a complete fresh read-only tracker snapshot")
    tracked = {pair(r) for r in tracker["rows"]}
    pool = {pair(c): c for c in verified["candidate_pool"]}
    excluded = set(pool) & tracked
    eligible = set(pool) - tracked
    roles = analysis.get("roles", [])
    seen, accessible, assessed, mandatory, gaps, composition = set(), set(), [], [], Counter(), Counter()
    priority = set(config["ranking_policy"]["capability_ids"])
    checkpoints = {check["persisted_at"]: verified}
    for prior in analysis.get("prior_checkpoints", []):
        if prior["run_date"] != check["run_date"] or prior["manifest"]["config_fingerprint"] != fingerprint(config):
            raise ValueError("Prior checkpoint must be from the same run and policy")
        prior_coverage = collection(prior, prior["manifest"])
        if not prior_coverage["collection_resolved"]:
            raise ValueError("Prior scoring checkpoint did not resolve its collection")
        checkpoints[prior["persisted_at"]] = prior_coverage
    for role in roles:
        key = pair(role)
        if key in seen or key not in eligible:
            raise ValueError("Analysis must be unique and in the tracker-deduplicated pool")
        seen.add(key)
        if role.get("jd_accessible") and role.get("jd_evidence") and role.get("jd_checked_at"):
            accessible.add(key)
        else:
            if role.get("fit_score") is not None or role.get("mandatory_gaps"):
                raise ValueError("Unreadable JDs must remain unscored")
            continue
        for gap in role.get("mandatory_gaps", []):
            if not all(gap.get(k) for k in ("category", "jd_requirement", "resume_gap")):
                raise ValueError("Mandatory gaps require JD requirement and resume evidence gap")
            gaps[gap["category"]] += 1
        matched = role.get("supported_capabilities", [])
        if any(c not in priority for c in matched):
            raise ValueError("Unknown ranking capability")
        if matched and (not isinstance(role.get("capability_evidence"), dict) or
                        any(not role["capability_evidence"].get(c) for c in matched)):
            raise ValueError("Priority matches require resume-to-JD evidence")
        composition.update(set(matched) or {"other_coherent_roles"})
        if role.get("mandatory_gap_excluded"):
            if not role.get("mandatory_gaps") or role.get("fit_score") is not None:
                raise ValueError("Mandatory-gap exclusions require evidence and remain unscored")
            mandatory.append(role)
        score = role.get("fit_score")
        if score is not None:
            assessed_at = datetime.fromisoformat(role.get("assessed_at", ""))
            checkpoint_time = role.get("collection_checkpoint", check["persisted_at"])
            if checkpoint_time not in checkpoints or key not in {pair(c) for c in checkpoints[checkpoint_time]["candidate_pool"]}:
                raise ValueError("Role must reference the persisted checkpoint containing its card")
            persisted_at = datetime.fromisoformat(checkpoint_time)
            if assessed_at.tzinfo is None or assessed_at < persisted_at:
                raise ValueError("Assessment timestamp must follow the persisted collection checkpoint")
            if type(score) not in (int, float) or not 0 <= score <= 10 or not role.get("fit_rationale"):
                raise ValueError("Scores require valid range and resume-grounded rationale")
            assessed.append(role)
    ranked = sorted(assessed, key=lambda r: (-r["fit_score"], -len(set(r.get("supported_capabilities", []))), pair(r)))
    coverage = verified["coverage_status"]
    # A first round below KPI requires round two, within existing day windows.
    second_required = check["manifest"]["round"] == 1 and len(assessed) < config["daily_report_target"]
    if second_required:
        coverage = "incomplete_coverage"
    metrics = {"captured_unique_cards": len(pool), "tracker_exclusions": len(excluded),
               "eligible_unique_cards": len(eligible), "accessible_jds": len(accessible),
               "assessed_roles": len(assessed), "score_at_least_7": sum(r["fit_score"] >= 7 for r in assessed),
               "score_below_6": sum(r["fit_score"] < 6 for r in assessed),
               "mandatory_gap_exclusions": len(mandatory), "coverage_status": coverage,
               "unassessed_eligible_cards": len(eligible - {pair(r) for r in assessed}),
               "round_two_required": second_required,
               "composition": dict(sorted(composition.items())), "mandatory_gap_categories": dict(sorted(gaps.items()))}
    page_yield = []
    for row in check["coverage"]:
        captured = {pair(c) for c in check["candidate_cards"] if c["cell_id"] == row["cell_id"] and c["page"] == row["page"]}
        page_yield.append({**row, "unique_card_count": len(captured),
                           "tracker_excluded_count": len(captured & tracked), "jd_read_count": len(captured & accessible)})
    round_counts = {}
    for round_number in (1, 2):
        cell_ids = {c["cell_id"] for c in check["manifest"]["cells"] if c["round"] == round_number}
        captured = {pair(c) for c in check["candidate_cards"] if c["cell_id"] in cell_ids}
        round_counts[str(round_number)] = {"captured_unique_cards": len(captured),
            "tracker_exclusions": len(captured & tracked), "accessible_jds": len(captured & accessible),
            "assessed_roles": sum(pair(r) in captured for r in assessed),
            "score_at_least_7": sum(pair(r) in captured and r["fit_score"] >= 7 for r in assessed),
            "score_below_6": sum(pair(r) in captured and r["fit_score"] < 6 for r in assessed),
            "mandatory_gap_exclusions": sum(pair(r) in captured for r in mandatory)}
        round_composition, round_gaps = Counter(), Counter()
        for role in roles:
            if pair(role) in captured & accessible:
                round_composition.update(set(role.get("supported_capabilities", [])) or {"other_coherent_roles"})
                round_gaps.update(gap["category"] for gap in role.get("mandatory_gaps", []))
        round_counts[str(round_number)]["composition"] = dict(sorted(round_composition.items()))
        round_counts[str(round_number)]["mandatory_gap_categories"] = dict(sorted(round_gaps.items()))
    return {"run_date": check["run_date"], "config_fingerprint": fingerprint(config),
            "strong_fit_yield": metrics, "ranked_roles": ranked,
            "round_yield": round_counts,
            "coverage_ledger": page_yield,
            "mandatory_gap_roles": mandatory, "tracker_excluded_pairs": sorted(excluded),
            "coverage": verified, "interpretation": "Incomplete coverage; market supply unknown" if coverage != "complete" else
            "Observed filtered supply and yield only; changes do not establish market-wide scarcity or causation"}


def study(start, config=None):
    config = config or read(DEFAULT_CONFIG)
    day, slots = date.fromisoformat(start), []
    # Monday has different authorized windows; mixing it would not be identical filters.
    target_days = config.get("measurement", {}).get("days", 10)
    while len(slots) < target_days:
        if day.weekday() in (1, 2, 3, 4):
            slots.append({"date": day.isoformat(), "status": "not_collected", "strong_fit_yield": None})
        day += timedelta(days=1)
    return {"created_at": datetime.now(timezone.utc).isoformat(), "config_fingerprint": fingerprint(config),
            "filter_policy": config, "slots": slots,
            "comparison_rule": "Only complete Tuesday-Friday runs with this exact fingerprint; missing/blocked runs remain unknown, never zeros. Keep round-one and expansion evidence separate. Monday is excluded because its windows differ.",
            "dimensions": {"supply": "captured_unique_cards (observed cards, not board result totals)",
                           "tracker_depletion": "tracker_exclusions and exclusions / captured_unique_cards",
                           "composition_and_gaps": "composition, mandatory_gap_categories and score bands; descriptive, not causal",
                           "coverage": "coverage_status and exact missing/blocked cells"}}


def record_study(study_artifact, daily):
    if daily["config_fingerprint"] != study_artifact["config_fingerprint"]:
        raise ValueError("Noncomparable query/filter policy; do not mix fingerprints")
    slots = [s for s in study_artifact["slots"] if s["date"] == daily["run_date"]]
    if len(slots) != 1:
        raise ValueError("Run date is outside the ten comparable weekday slots")
    slot = slots[0]
    slot.update({"status": daily["strong_fit_yield"]["coverage_status"],
                 "strong_fit_yield": daily["strong_fit_yield"], "round_yield": daily["round_yield"],
                 "missing_or_invalid_cells": daily["coverage"]["missing_or_invalid_cells"],
                 "missing_or_invalid_page_cells": daily["coverage"]["missing_or_invalid_page_cells"],
                 "blocked_cells": daily["coverage"]["blocked_cells"]})
    complete = [s for s in study_artifact["slots"] if s["status"] == "complete"]
    study_artifact["complete_comparable_days"] = len(complete)
    comparisons = []
    for previous, current in zip(complete, complete[1:]):
        a, b = previous["round_yield"]["1"], current["round_yield"]["1"]
        comparisons.append({"from": previous["date"], "to": current["date"],
                            "round_one_deltas": {k: b[k] - a[k] for k in a if isinstance(a[k], int)},
                            "composition_deltas": {k: b["composition"].get(k, 0) - a["composition"].get(k, 0)
                                                   for k in sorted(set(a["composition"]) | set(b["composition"]))},
                            "mandatory_gap_deltas": {k: b["mandatory_gap_categories"].get(k, 0) - a["mandatory_gap_categories"].get(k, 0)
                                                     for k in sorted(set(a["mandatory_gap_categories"]) | set(b["mandatory_gap_categories"]))},
                            "tracker_depletion_rates": [a["tracker_exclusions"] / a["captured_unique_cards"] if a["captured_unique_cards"] else None,
                                                        b["tracker_exclusions"] / b["captured_unique_cards"] if b["captured_unique_cards"] else None],
                            "interpretation": "Descriptive changes only; review composition/gap counts and JD access before attributing causes"})
    study_artifact["comparisons"] = comparisons
    return study_artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("date")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--output", required=True)
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p = sub.add_parser("checkpoint")
    p.add_argument("input")
    p.add_argument("manifest")
    p.add_argument("--output", required=True)
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p = sub.add_parser("measure")
    p.add_argument("checkpoint")
    p.add_argument("analysis")
    p.add_argument("--output", required=True)
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p = sub.add_parser("study")
    p.add_argument("start")
    p.add_argument("--output", required=True)
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p = sub.add_parser("study-record")
    p.add_argument("study")
    p.add_argument("daily")
    p.add_argument("--output", required=True)
    args = parser.parse_args()
    config = read(args.config) if hasattr(args, "config") else None
    if args.command == "plan":
        result = plan(args.date, args.round, config)
    elif args.command == "checkpoint":
        result = checkpoint(read(args.input), read(args.manifest), config)
    elif args.command == "measure":
        result = measure(read(args.checkpoint), read(args.analysis), config)
    elif args.command == "study":
        result = study(args.start, config)
    else:
        result = record_study(read(args.study), read(args.daily))
    save(args.output, result)
    print(f"Saved {args.command}: {args.output}")


if __name__ == "__main__":
    main()
