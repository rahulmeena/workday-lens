# Prompt regression experiments

[Evaluation overview](evaluation.md) · [Judge scores](evaluation-judges.md) · [Runtime and inventory](evaluation-models.md) · [Prompt experiments](evaluation-prompts.md)

Four retained 50-card sweeps compare prompt variants on the same source-ID set **within each sweep**. All variants are shown, including regressions. These are development/tuning samples, not a held-out test set. Baseline rows labeled `default_existing` reuse stored outputs; missing fresh timing is not zero latency. The experiment groups are separate from the 29 base-identity database count. The Gemma group uses the historical directory/runner label; the per-card file does not independently record the model ID.

The [original scoring implementation](../evaluations/prompt_metrics.py) combines lexical similarity and structural checks: 22% headline similarity + 38% summary similarity + 20% field agreement + 10% evidence-token overlap + 8% non-collapse heuristic + 2% confidence-range heuristic. It is **not semantic accuracy or an LLM-judge score**.

SequenceMatcher measures normalized character-sequence similarity. Field agreement combines exact categorical matches and lexical overlap against silver output. The non-collapse score penalizes missing/duplicated fields, copied titles and instruction leakage. Confidence-range checks do not establish calibration.

## Qwen3.6-27B · initial sweep

| Prompt variant | N | Combined | Headline | Summary | Fields | Evidence | Non-collapse | Parse % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `default_existing` | 50 | 0.3724 | 0.4640 | 0.0793 | 0.5968 | 0.2347 | 0.9676 | 100 |
| `qwen36_27b_generic_v1` | 50 | 0.3795 | 0.4542 | 0.1015 | 0.5724 | 0.2651 | 1.0000 | 100 |
| `qwen36_27b_generic_v2` | 50 | 0.3784 | 0.4616 | 0.0988 | 0.5656 | 0.2625 | 1.0000 | 100 |
| `qwen36_default_chatml` | 50 | 0.3653 | 0.4475 | 0.0777 | 0.5741 | 0.2251 | 1.0000 | 100 |
| `qwen_small_generic_v2` | 50 | 0.3643 | 0.4372 | 0.0982 | 0.5153 | 0.2831 | 0.9928 | 100 |

[Numeric results and timing](../evaluations/results/prompts/qwen36-27b-full50.csv). Source-set equality was checked during export; private source IDs and activity text are omitted.

## Qwen3.5-4B · initial sweep

| Prompt variant | N | Combined | Headline | Summary | Fields | Evidence | Non-collapse | Parse % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `default_existing` | 50 | 0.3153 | 0.3714 | 0.0604 | 0.5011 | 0.1648 | 0.9244 | 100 |
| `qwen36_27b_generic_v1` | 50 | 0.3106 | 0.4009 | 0.0544 | 0.4359 | 0.1479 | 0.9964 | 100 |
| `qwen36_27b_generic_v2` | 50 | 0.3234 | 0.4158 | 0.0672 | 0.4682 | 0.1273 | 1.0000 | 100 |
| `qwen36_default_chatml` | 50 | 0.3149 | 0.3861 | 0.0512 | 0.4846 | 0.1615 | 0.9676 | 100 |
| `qwen_small_generic_v1` | 50 | 0.3082 | 0.3899 | 0.0675 | 0.4138 | 0.1455 | 0.9928 | 100 |
| `qwen_small_generic_v2` | 50 | 0.3082 | 0.3899 | 0.0675 | 0.4138 | 0.1455 | 0.9928 | 100 |

[Numeric results and timing](../evaluations/results/prompts/qwen35-4b-full50.csv). Source-set equality was checked during export; private source IDs and activity text are omitted.

## Qwen3.5-4B · follow-up sweep

| Prompt variant | N | Combined | Headline | Summary | Fields | Evidence | Non-collapse | Parse % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `qwen35_4b_generic_v4` | 50 | 0.3301 | 0.4211 | 0.0690 | 0.4815 | 0.1520 | 0.9964 | 100 |
| `qwen35_4b_generic_v5` | 50 | 0.3291 | 0.4305 | 0.0652 | 0.4825 | 0.1339 | 0.9964 | 100 |
| `qwen35_4b_generic_v6` | 50 | 0.3269 | 0.4192 | 0.0769 | 0.4580 | 0.1382 | 1.0000 | 100 |
| `qwen35_4b_generic_v8` | 50 | 0.3374 | 0.4617 | 0.0715 | 0.4750 | 0.1395 | 0.9964 | 100 |
| `qwen36_27b_generic_v2` | 50 | 0.3234 | 0.4158 | 0.0672 | 0.4682 | 0.1273 | 1.0000 | 100 |

[Numeric results and timing](../evaluations/results/prompts/qwen35-4b-followup50.csv). Source-set equality was checked during export; private source IDs and activity text are omitted.

## Gemma 4 12B experiment · MLX runner

| Prompt variant | N | Combined | Headline | Summary | Fields | Evidence | Non-collapse | Parse % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `default` | 50 | 0.3367 | 0.4655 | 0.0780 | 0.4503 | 0.1459 | 1.0000 | 100 |
| `gemma4_generic_v1` | 50 | 0.3558 | 0.4465 | 0.0742 | 0.5367 | 0.2205 | 1.0000 | 100 |
| `gemma4_generic_v2` | 50 | 0.3571 | 0.4404 | 0.0747 | 0.5572 | 0.2040 | 1.0000 | 100 |
| `lfm_minimal_summary_v6` | 50 | 0.2345 | 0.4115 | 0.0712 | 0.0844 | 0.0000 | 1.0000 | 100 |

[Numeric results and timing](../evaluations/results/prompts/gemma4-12b-full50.csv). Source-set equality was checked during export; private source IDs and activity text are omitted.

## What these experiments establish

The retained sweeps show an iterative process: choose a fixed sample, compare variants, inspect failure modes, retain the full result table, and run broader evaluation for selected variants. Some changes reduce the heuristic score. A prompt selected on these samples needs a separate holdout and source-grounded judgment before claiming a general quality gain.

The database also contains later full-run prompt variants for Qwen3.5-0.8B and Qwen3.5-4B. Their aggregate judge scores are in the main result tables, but their input-snapshot hashes differ from the original runs. A difference between those aggregate scores is not a clean prompt-only causal effect.
