"""Validate a user-owned search configuration without reading private data."""
import json
import sys
from pathlib import Path


SOURCES = ("LinkedIn", "Indeed", "Eluta")


def validate(path: Path) -> list[str]:
    errors = []
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Cannot read JSON config: {exc}"]

    for key in ("source_order", "lanes", "core_queries", "fallback_queries", "sources",
                "rounds", "daily_report_target", "ranking_policy"):
        if key not in config:
            errors.append(f"Missing required key: {key}")
    if errors:
        return errors

    if config["source_order"] != list(SOURCES):
        errors.append(f"source_order must be {list(SOURCES)}")
    lanes = config["lanes"]
    if not isinstance(lanes, list) or not lanes or len(lanes) != len(set(lanes)):
        errors.append("lanes must be a non-empty list of unique names")
        lanes = []
    for key in ("core_queries", "fallback_queries"):
        mapping = config[key]
        if not isinstance(mapping, dict) or set(mapping) != set(lanes):
            errors.append(f"{key} must contain exactly one entry for each lane")
            continue
        for lane, queries in mapping.items():
            if not isinstance(queries, list) or not queries or any(not isinstance(q, str) or not q.strip() for q in queries):
                errors.append(f"{key}[{lane!r}] must be a non-empty list of query strings")
            if key == "fallback_queries" and isinstance(queries, list) and len(queries) != 1:
                errors.append(f"fallback_queries[{lane!r}] must contain exactly one bounded query")

    sources = config["sources"]
    if not isinstance(sources, dict) or set(sources) != set(SOURCES):
        errors.append(f"sources must define exactly {list(SOURCES)}")
    else:
        for source, settings in sources.items():
            for key in ("monday_days", "other_weekday_days", "radius_km", "sort", "pages_per_lane"):
                if key not in settings:
                    errors.append(f"sources[{source!r}] is missing {key!r}")
            for key in ("monday_days", "other_weekday_days"):
                days = settings.get(key)
                if not isinstance(days, list) or not days or any(type(day) is not int or day < 1 for day in days):
                    errors.append(f"sources[{source!r}][{key!r}] must be a non-empty list of positive day windows")
            radius = settings.get("radius_km")
            if radius is not None and (type(radius) not in (int, float) or radius <= 0):
                errors.append(f"sources[{source!r}].radius_km must be positive or null")
            if not isinstance(settings.get("sort"), str) or not settings["sort"].strip():
                errors.append(f"sources[{source!r}].sort must be a non-empty string")
            pages = settings.get("pages_per_lane")
            if type(pages) is not int or pages < 1:
                errors.append(f"sources[{source!r}].pages_per_lane must be a positive integer")

    rounds = config["rounds"]
    if not isinstance(rounds, dict) or rounds.get("maximum") not in (1, 2):
        errors.append("rounds.maximum must be 1 or 2")
    target = config["daily_report_target"]
    if type(target) is not int or target < 1:
        errors.append("daily_report_target must be a positive integer")
    caps = config["ranking_policy"].get("capability_ids") if isinstance(config["ranking_policy"], dict) else None
    if not isinstance(caps, list) or len(caps) != len(set(caps)) or any(not isinstance(v, str) or not v for v in caps):
        errors.append("ranking_policy.capability_ids must be a list of unique non-empty strings")
    return errors


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config/search.json")
    errors = validate(path)
    if errors:
        print("Configuration invalid:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Configuration valid: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
