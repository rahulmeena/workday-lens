#!/usr/bin/env python3
"""Export aggregate benchmark results without exporting desktop activity.

Python standard library only. The input must be a quiescent SQLite snapshot
with no WAL. No application imports, capture workers, inference, or network IO.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import statistics

QUALITY_FIELDS = (
    "final_score", "silver_agreement_normalized", "silver_agreement_score_1_to_5",
    "faithfulness_score", "coverage_score", "precision_score", "usefulness_score",
    "noise_score", "hallucination_rate", "key_facts_total", "key_facts_matched",
    "candidate_facts_total", "candidate_facts_supported", "candidate_facts_irrelevant",
    "total_claim_count", "supported_claim_count", "unsupported_claim_count",
    "contradicted_claim_count", "over_specific_claim_count",
)
# Behavioral/mental-state inferences and free-text explanations are deliberately
# excluded. These fields describe workflow opportunities, not model accuracy.
AUTOMATION_FIELDS = (
    "final_score", "automation_opportunity_score", "ai_delegation_score",
    "shortcut_opportunity_score", "repetition_score", "automatable_task_count",
    "ai_delegable_task_count", "shortcut_task_count", "repetitive_task_count",
    "repetition_instances", "estimated_effort_savings_minutes",
)
SUITES = {
    "workday_lens_llm_judge_eval_v1": "reference",
    "workday_lens_source_grounded_eval_v1": "source_grounded",
    "workday_lens_automation_opportunity_eval_v1": "automation",
}
HARDWARE_FIELDS = ("platform", "chip", "unified_memory_gb", "runtime", "quant", "llama_cpp_version", "mlx_lm_version", "mlx_vlm_version", "mlx_version", "torch_version", "transformers_version", "dtype", "device", "ctx_size", "predict_tokens", "prompt_style")


def public_name(name: str) -> str:
    if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name):
        if Path(name).name == "HRM-Text-1B-Q5_K_M.gguf":
            return "sinimiini/HRM-Text-1B-GGUF:Q5_K_M"
        raise ValueError("Unreviewed local model path; add a public alias first")
    if not re.fullmatch(r"[A-Za-z0-9_./:+-]+", name):
        raise ValueError("Unreviewed model identifier")
    return name


def base_model(name: str) -> str:
    """Collapse packaging, quantization, prompt suffixes and runtime aliases.

    This is an identity-counting convention, not a claim of identical weights.
    Instruct/Thinking and parameter-size distinctions are preserved.
    """
    name = public_name(name).split("/")[-1].split("+")[0].split(":")[0]
    name = re.sub(r"-(?:GGUF|MLX)(?:-8bit)?$", "", name, flags=re.I)
    name = re.sub(r"-(?:Q4_K_M|UD-IQ2_M|bf16|5bit|8bit|OptiQ-4bit)$", "", name, flags=re.I)
    name = re.sub(r"-(?:MTP-IMAT-Q4_K_M-Q8nextn|MTP-Q4_K_M-Q8nextn|MTP)$", "", name)
    return name.replace("gemma-3-270m-it-qat", "gemma-3-270m-it")


def numeric(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def mean(values):
    values = [float(v) for v in values if numeric(v)]
    return round(statistics.mean(values), 6) if values else None


def percentile(values, fraction):
    """Nearest-rank percentile; non-positive/unrecorded latencies excluded."""
    values = sorted(v for v in values if numeric(v) and v > 0)
    return values[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def write_csv(path: Path, rows: list[dict]):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def aggregate_generation(rows):
    statuses = Counter(r["status"] for r in rows)
    succeeded = [r for r in rows if r["status"] == "succeeded"]
    latencies = [r["latency_ms"] for r in succeeded if r["latency_ms"] > 0]
    return {
        "records": len(rows), "succeeded": statuses["succeeded"],
        "failed": statuses["failed"], "other": len(rows) - statuses["succeeded"] - statuses["failed"],
        "success_rate": round(statuses["succeeded"] / len(rows), 6),
        "teacher_records": sum(r["generation_role"] == "teacher" for r in rows),
        "source_items": len({(r["level"], r["source_id"]) for r in rows}),
        "json_valid_rate": mean([int(bool(r["json_parse_success"])) for r in rows]),
        "schema_valid_rate": mean([int(bool(r["schema_validation_success"])) for r in rows]),
        "timed_successes": len(latencies), "mean_latency_ms": mean(latencies),
        "p50_latency_ms": percentile(latencies, .5), "p95_latency_ms": percentile(latencies, .95),
        "mean_input_tokens": mean([r["prompt_tokens"] for r in succeeded]),
        "mean_output_tokens": mean([r["completion_tokens"] for r in succeeded]),
        "total_recorded_tokens": sum(r["total_tokens"] for r in rows),
        "cost_records": sum(numeric(r["estimated_cost"]) for r in succeeded),
        "mean_estimated_cost": mean([r["estimated_cost"] for r in succeeded]),
    }


def aggregate_judge(rows, fields):
    passed = [r for r in rows if r["status"] == "succeeded"]
    result = {"records": len(rows), "succeeded": len(passed), "failed": sum(r["status"] == "failed" for r in rows)}
    for field in fields:
        values = [r["scores"].get(field) for r in passed]
        result[field] = mean(values)
        result[field + "_n"] = sum(numeric(v) for v in values)
    return result


def export(database: Path, output: Path):
    database = database.resolve(strict=True)
    if Path(str(database) + "-wal").exists():
        raise ValueError("Export a consistent database snapshot first; a WAL is present")
    before = database.stat()
    connection = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    # Do not SELECT *: raw inputs, summaries, screenshots, errors, paths and
    # credentials must never enter a public export.
    generations = [dict(row) for row in connection.execute("""
        SELECT id,session_id,generation_role,provider,model_name,modality,level,
               source_id,status,prompt_tokens,completion_tokens,total_tokens,
               latency_ms,estimated_cost,json_parse_success,schema_validation_success,
               hyperparameters_json,created_at,updated_at
        FROM llm_benchmark_generations ORDER BY id
    """)]
    keys = sorted({(r["provider"], public_name(r["model_name"]), r["modality"]) for r in generations})
    ids = {key: f"C{i:02}" for i, key in enumerate(keys, 1)}
    groups = defaultdict(list)
    levels = defaultdict(list)
    generation_config = {}
    hardware = defaultdict(set)
    for row in generations:
        key = row["provider"], public_name(row["model_name"]), row["modality"]
        config = ids[key]
        generation_config[row["id"]] = config
        groups[config].append(row)
        levels[(config, row["level"])].append(row)
        params = json.loads(row.pop("hyperparameters_json") or "{}")
        for field in HARDWARE_FIELDS:
            value = params.get(field)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                # Defensive guard against a path accidentally stored in metadata.
                if isinstance(value, str) and ("/Users/" in value or "\\" in value or len(value) > 100):
                    continue
                hardware[(config, field)].add(str(value))
    config_rows = []
    for key, config in ids.items():
        provider, model, modality = key
        config_rows.append({
            "config_id": config, "base_model": base_model(model), "model": model,
            "kind": "proprietary_api" if provider == "openai" else "local_weights",
            "runtime": provider, "modality": modality,
            "sessions": len({r["session_id"] for r in groups[config]}),
            **aggregate_generation(groups[config]),
        })
    metric_groups = defaultdict(list)
    metric_record_counts = Counter()
    for row in connection.execute("SELECT generation_id,metric_type,metric_name,value_float FROM llm_benchmark_metrics"):
        key = generation_config[row["generation_id"]], row["metric_type"], row["metric_name"]
        metric_record_counts[key] += 1
        if numeric(row["value_float"]):
            metric_groups[key].append(row["value_float"])
    metric_rows = [{"config_id": k[0], "metric_type": k[1], "metric": k[2],
                    "records": n, "numeric_n": len(metric_groups[k]), "mean": mean(metric_groups[k])}
                   for k, n in sorted(metric_record_counts.items())]
    runs = {}
    for row in connection.execute("SELECT id,config_json FROM llm_benchmark_judge_runs"):
        schema = json.loads(row["config_json"]).get("judge_schema")
        if schema not in SUITES:
            raise ValueError("Unreviewed judge schema")
        runs[row["id"]] = SUITES[schema]
    run_ids = {rid: f"R{i:02}" for i, rid in enumerate(sorted(runs), 1)}
    judge_groups, judge_levels, judge_runs = defaultdict(list), defaultdict(list), defaultdict(list)
    judge_candidates, judged_configs = set(), set()
    judge_statuses = Counter()
    judge_sources = set()
    for row in connection.execute("""
        SELECT run_id,candidate_generation_id,level,source_id,judge_model,status,parsed_output_json
        FROM llm_benchmark_judge_results ORDER BY id
    """):
        suite, run = runs[row["run_id"]], run_ids[row["run_id"]]
        config = generation_config[row["candidate_generation_id"]]
        judge = public_name(row["judge_model"])
        fields = AUTOMATION_FIELDS if suite == "automation" else QUALITY_FIELDS
        parsed = json.loads(row["parsed_output_json"] or "{}")
        entry = {"status": row["status"], "scores": {k: parsed[k] for k in fields if numeric(parsed.get(k))}}
        judge_groups[(run, suite, judge, config)].append(entry)
        judge_levels[(run, suite, judge, config, row["level"])].append(entry)
        judge_runs[(run, suite, judge)].append(entry)
        judge_statuses[row["status"]] += 1
        if row["status"] == "succeeded":
            judge_candidates.add(row["candidate_generation_id"])
            judged_configs.add(config)
            judge_sources.add((row["level"], row["source_id"]))
    judge_rows = [{"run": k[0], "suite": k[1], "judge": k[2], "config_id": k[3],
                   **aggregate_judge(rows, AUTOMATION_FIELDS if k[1] == "automation" else QUALITY_FIELDS)}
                  for k, rows in sorted(judge_groups.items())]
    judge_level_rows = [{"run": k[0], "suite": k[1], "judge": k[2], "config_id": k[3], "level": k[4],
                         **aggregate_judge(rows, AUTOMATION_FIELDS if k[1] == "automation" else QUALITY_FIELDS)}
                        for k, rows in sorted(judge_levels.items())]
    run_rows = [{"run": k[0], "suite": k[1], "judge": k[2],
                 **aggregate_judge(rows, AUTOMATION_FIELDS if k[1] == "automation" else QUALITY_FIELDS)}
                for k, rows in sorted(judge_runs.items())]
    connection.close()
    after = database.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("Database changed during export; results not written")
    output.mkdir(parents=True, exist_ok=True)
    tables = {
        "configurations.csv": config_rows,
        "generation-levels.csv": [{"config_id": k[0], "level": k[1], **aggregate_generation(v)} for k, v in sorted(levels.items())],
        "stored-metrics.csv": metric_rows, "judge-scores.csv": judge_rows,
        "judge-levels.csv": judge_level_rows, "judge-runs.csv": run_rows,
        "runtime-metadata.csv": [{"config_id": k[0], "field": k[1], "recorded_values": " | ".join(sorted(v))} for k, v in sorted(hardware.items())],
    }
    for name, rows in tables.items():
        write_csv(output / name, rows)
    statuses = Counter(r["status"] for r in generations)
    summary = {
        "export_schema": "workday-lens-aggregate-v1", "published_on": "2026-11-10",
        "generation_date_range_utc": [min(r["created_at"] for r in generations)[:10], max(r["updated_at"] for r in generations)[:10]],
        "generation_records": len(generations), "generation_statuses": dict(sorted(statuses.items())),
        "generation_sessions": len({r["session_id"] for r in generations}),
        "raw_dashboard_configurations": len({(r["provider"], r["model_name"], r["modality"]) for r in generations}),
        "configurations": len(config_rows),
        "local_model_identities": len({r["base_model"] for r in config_rows if r["kind"] == "local_weights"}),
        "api_model_identities": len({r["base_model"] for r in config_rows if r["kind"] == "proprietary_api"}),
        "local_identities_with_success": len({r["base_model"] for r in config_rows if r["kind"] == "local_weights" and r["succeeded"]}),
        "source_items": len({(r["level"], r["source_id"]) for r in generations}),
        "levels": sorted({r["level"] for r in generations}),
        "judge_runs": len(runs), "judge_statuses": dict(sorted(judge_statuses.items())),
        "unique_judged_generations": len(judge_candidates), "unique_judged_source_items": len(judge_sources),
        "configurations_with_successful_judgments": len(judged_configs),
        "stored_metric_records": sum(metric_record_counts.values()),
        "stored_metric_names": len({k[2] for k in metric_record_counts}),
        "csv_sha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in tables},
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("evaluations/results"))
    args = parser.parse_args()
    export(args.database, args.output)
