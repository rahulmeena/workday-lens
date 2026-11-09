# Evaluation data and tooling

Start with the [evaluation report](../docs/evaluation.md) or the [open-weight/proprietary comparison](../docs/evaluation-comparison.md). This directory contains aggregate results from the historical benchmark, the original judge rubrics/schemas, a reusable prompt formatter, the original prompt-scoring heuristic, and the code used to prepare the public report.

No private activity dataset, screenshots, source IDs, individual model outputs, judge rationales, API batch IDs, credentials or runtime secrets are included. CSVs are real aggregate measurements, not demo fixtures. The clinical/behavioral inference fields from the original experimental automation schema are intentionally not exported.

## Public artifacts

| Artifact | Contents |
| --- | --- |
| [summary.json](results/summary.json) | Counts, date range, counting conventions and SHA-256 hashes of the main CSVs |
| [configurations.csv](results/configurations.csv) | Every normalized model/runtime/modality/prompt configuration, including failures |
| [generation-levels.csv](results/generation-levels.csv) | Generation metrics broken down by hierarchy level |
| [stored-metrics.csv](results/stored-metrics.csv) | All 32 historical metric names, numeric denominators and means |
| [judge-scores.csv](results/judge-scores.csv) | Scores by saved run, actual judge and configuration |
| [judge-levels.csv](results/judge-levels.csv) | Judge scores by hierarchy level |
| [judge-runs.csv](results/judge-runs.csv) | Run totals; mixed-judge run split by actual result identity |
| [runtime-metadata.csv](results/runtime-metadata.csv) | Available runtime/hardware/quantization settings; incomplete across older runs |
| [prompts/](results/prompts/) | Four retained 50-card prompt sweeps, exported from their per-card records |
| [rubrics/](rubrics/) | Original reference, source-grounded and opportunity instructions and output schemas |
| [judge_prompts.py](judge_prompts.py) | Builds a rubric prompt around caller-supplied evidence; no inference/network calls |
| [prompt_metrics.py](prompt_metrics.py) | Extracted original lexical/structural prompt-scoring implementation |

The project license covers these original scripts, rubrics and aggregate results. Referenced models retain their own licenses; no weights are distributed here. “Local/open-weight” is used descriptively, not as a claim that every model has an OSI-approved license.

## Regenerate the public tables

From the repository root, with Python 3.12:

```bash
python evaluations/build_report.py
python -m unittest evaluations.test_exports -v
```

The tables use only the standard library. The grouped model comparison selects run R05, reference scoring, GPT-5.4-mini judgments and text-only candidates, then sorts recorded mean scores within each model group. It does not combine different judge runs or assert matched evidence sets. For both charts:

```bash
python -m pip install -r evaluations/requirements-report.txt
python evaluations/build_report.py --plot
```

## Re-export from a private benchmark snapshot

The original database is not required to read or regenerate this public report. A maintainer with a compatible, quiescent database snapshot can run:

```bash
python evaluations/export_results.py \
  --database /path/to/private-benchmark-snapshot.db \
  --output evaluations/results

python evaluations/export_prompt_experiment.py \
  --input /path/to/private-prompt-experiment.jsonl \
  --experiment public-experiment-label \
  --output evaluations/results/prompts/public-experiment-label.csv
```

The database exporter opens SQLite read-only/immutable and refuses an active WAL; stop writers and use a consistent snapshot. It verifies that the database file did not change during extraction. It reads explicit columns, exports allowlisted numeric aggregates and metadata, and replaces one known local-path model alias. Unknown local model paths fail closed for review. Do not point this command at a live capture database.

The public files let readers inspect/recompute aggregation and report rendering. They do **not** let readers independently rerun historical model inference: the private evidence, model revisions, prompts and machine/runtime configuration would also be required. The extracted rubric and scoring utilities are not presented as the full historical orchestration service.

## Provenance and scope

This export comes from the retained combined Windows/macOS benchmark archive used by the development dashboards, with generation dates May 10–July 1, 2026. It covers five saved judge runs. Configuration IDs (`C01`…) and run IDs (`R01`…) are public report identifiers, not private database identifiers.

One local-file HRM alias is normalized to the same public model identifier. Base identities collapse quantization, packaging, runtime and prompt suffixes while preserving size and instruction/Thinking distinctions. MTP variants remain separate configuration rows but share a base identity. A configuration is a reporting group, not necessarily a single immutable set of hyperparameters.

Four standalone 50-card prompt sweeps are reported separately; they are not added to the main database model/generation totals. Smoke/debug experiments and files with uncertain model identity are not used to inflate the headline count.
