#!/usr/bin/env python3
"""Reduce a private prompt experiment JSONL to a numeric, public CSV."""
from __future__ import annotations
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import re
import statistics

FIELDS = ("combined", "headline_sim", "summary_sim", "field_score", "evidence_overlap", "noncollapse", "confidence_sanity", "elapsed_ms")


def export(source: Path, output: Path, experiment: str):
    if not re.fullmatch(r"[a-z0-9-]+", experiment):
        raise ValueError("Use a public experiment label")
    groups = defaultdict(list)
    with source.open() as handle:
        for line in handle:
            row = json.loads(line)
            variant = row["variant"]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", variant):
                raise ValueError("Unreviewed variant label")
            groups[variant].append(row)
    source_sets = [{row["source_id"] for row in rows} for rows in groups.values()]
    if any(len(rows) != len({r["source_id"] for r in rows}) for rows in groups.values()):
        raise ValueError("Duplicate source items in a variant")
    same_sources = len({frozenset(s) for s in source_sets}) == 1
    result = []
    for variant, rows in sorted(groups.items()):
        item = {"experiment": experiment, "variant": variant, "n": len(rows), "same_source_set": same_sources}
        for field in FIELDS:
            values = [float(row[field]) for row in rows if isinstance(row.get(field), (int, float))]
            item[field] = round(statistics.mean(values), 6) if values else None
        item["parse_ok_rate"] = sum(bool(row["parse_ok"]) for row in rows) / len(rows)
        item["compacted_count"] = sum(bool(row["prompt_compacted"]) for row in rows)
        for field in ("predicted_per_second", "prompt_per_second"):
            values = [float(row[field]) for row in rows if isinstance(row.get(field), (int, float)) and row[field] > 0]
            item[field] = round(statistics.mean(values), 6) if values else None
            item[field + "_n"] = len(values)
        result.append(item)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--experiment", required=True)
    args = parser.parse_args()
    export(args.input, args.output, args.experiment)
