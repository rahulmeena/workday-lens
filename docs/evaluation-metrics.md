# Evaluation metric dictionary

[Evaluation overview](evaluation.md) · [All stored numeric aggregates](../evaluations/results/stored-metrics.csv)

The historical database contains 32 stored metric names. Each CSV row identifies its configuration, metric family, total record count, numeric count and mean. Missing values remain empty. The CSV preserves historical values even when a metric is a heuristic or placeholder; the status below governs interpretation.

| Family | Fields | Meaning / limitation |
| --- | --- | --- |
| Runtime | `latency_ms`, `input_tokens`, `output_tokens`, `total_tokens` | Recorded request/runtime telemetry; latency includes backend-specific overhead and is not decode tokens/second |
| Runtime | `json_parse_success`, `schema_validation_success` | Structural validity indicators, not factual correctness |
| Runtime | `image_count` | Number of prepared images associated with a generation |
| Runtime | `estimated_cost` | Historical configured price estimate; only 3,556 numeric records, not complete spend or current pricing |
| Perplexity | `perplexity` | **No numeric values**; unavailable, not zero |
| Faithfulness proxy | `evidence_coverage_score`, `unsupported_claim_count`, `contradicted_claim_count`, `over_specific_claim_count`, `uncertainty_count` | Candidate-emitted fields; self-report, not an independent judge |
| Faithfulness proxy | `unknown_rate` | Heuristic from unknown labels/fields, capped at 1; not an error rate |
| Silver agreement | `activity_type_match`, `productivity_match`, `focus_level_match` | Exact normalized categorical matches to a matching teacher output |
| Silver agreement | `primary_app_match`, `primary_project_match` | Normalized exact/string similarity to teacher fields |
| Silver agreement | `user_goal_similarity`, `specific_task_similarity`, `summary_similarity`, `evidence_similarity` | Normalized character-sequence similarity using Python SequenceMatcher; not embeddings, BLEU, ROUGE or an LLM judge |
| Silver agreement | `overall_silver_agreement_score` | Unweighted average of the nine stored agreement components; distinct from an LLM judge's `final_score` |
| Model gap | `score_gap_vs_teacher` | `1 - overall_silver_agreement_score`; not an independently measured quality gap |
| Model gap | `latency_savings_vs_teacher` | Teacher latency minus candidate latency for matching records; hardware/settings are not controlled |
| Hierarchical consistency | `child_summary_coverage_score`, `rollup_consistency_score` | The same lexical-similarity heuristic comparing a parent summary with concatenated child summaries |
| Hierarchical consistency | `missed_major_activity_count` | Heuristic `max(0, round((1 - coverage) * 3))`, not an observed omission count |
| Hierarchical consistency | `invented_activity_count` | Candidate-reported unsupported-claim count, not independent verification |
| Hierarchical consistency | `timeline_order_score` | **Constant placeholder of 1.0**, not a measured ordering score |

## LLM judge outputs

These live in separate judge-result tables, not the 32-name stored-metric table. The original [JSON schemas](../evaluations/rubrics/) define their ranges.

| Metric | Interpretation |
| --- | --- |
| `final_score` | Judge-produced 0–100 composite, retained without rescaling/recomputation |
| `faithfulness_score` | Degree of support for claims, penalizing contradiction/unsupported detail |
| `coverage_score` | Coverage of important reference/source facts |
| `precision_score` | Supported, relevant facts relative to candidate facts |
| `usefulness_score` | Judge assessment of usefulness for remembering work activity |
| `noise_score` | Irrelevant content; lower is better |
| `hallucination_rate` | Source-grounded unsupported-claim rate; absent in reference-only schema |
| `silver_agreement_score_1_to_5` | Original ordinal reference-agreement rubric |
| `silver_agreement_normalized` | Judge-emitted normalized agreement, retained as recorded; not assumed to equal a particular rescaling of the ordinal value |
| Claim/fact counts | Supported, unsupported, contradicted, over-specific, matched, total and irrelevant counts where present in the rubric |

`judge-scores.csv` and `judge-levels.csv` give each field its own `_n` denominator. Only successful judgments with finite numeric values contribute to a mean; failure, missing and zero are distinct. Historical dashboards applied a magnitude-based score normalization; this export instead preserves the schema's original 0–100 final-score scale and 0–1 component scales.

## Opportunity analysis

The public opportunity aggregates retain automation/delegation/shortcut/repetition scores, inferred task counts and estimated effort savings. They are exploratory descriptions of activity, not objective quality, causality or demonstrated time saved. Different cohorts overlap. Behavioral/mental-state fields and free-text explanations from the original experimental rubric are excluded from publication. Their presence in the archived schema documents what was tried; it does not validate those constructs.

## Runtime aggregation

The model inventory computes success and validity rates over all persisted generation records. Timing statistics use only successful records with positive latency. Median and p95 use the nearest-rank convention. Token averages use successful generations; total recorded tokens include all stored statuses. Exported estimated-cost means include only non-null costs. Provider token accounting and latency boundaries can differ.

The [runtime metadata CSV](../evaluations/results/runtime-metadata.csv) contains only allowlisted hardware/runtime fields. Empty metadata is unknown, not evidence of the same hardware. Retry attempts are not necessarily separate generation rows; these counts describe persisted records, not billed API calls.
