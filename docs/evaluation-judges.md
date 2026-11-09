# LLM judge results

[Evaluation overview](evaluation.md) · [Judge scores](evaluation-judges.md) · [Runtime and inventory](evaluation-models.md) · [Prompt experiments](evaluation-prompts.md)

These are retrospective, model-judged scores on private activity evidence. Rows have different sample counts and sometimes different source subsets, prompt settings, and hierarchy levels. They are not a controlled leaderboard or human-validated accuracy scores. All configurations present in each completed judge cohort are shown, with failures retained.

`Final` uses the original 0–100 scale. Faithfulness, coverage, precision, usefulness, noise and hallucination rate use 0–1. A dash means not recorded. CSV columns ending in `_n` give each metric's non-null denominator. Aggregation is the arithmetic mean over successful judgments; failed judgments never become zero quality scores.

## Reference · gpt-5.4 · R03

GPT-5.4 text+image is a **reference-model control**, not an independent candidate result: comparison against its own silver labels explains its near-perfect agreement. The mixed first-pass run is split by each result's actual judge model.

| ID | Configuration | N ok | Failed | Final | Faithful | Coverage | Precision | Useful | Noise | Hallucination |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | Qwen3-1.7B-GGUF:Q4_K_M · text | 474 | 114 | 28.34 | 0.22 | 0.24 | 0.33 | 0.25 | 0.15 | — |
| C02 | Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M · text | 50 | 0 | 8.94 | 0.09 | 0.05 | 0.10 | 0.07 | 0.33 | — |
| C03 | Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M · text | 425 | 163 | 28.09 | 0.21 | 0.24 | 0.33 | 0.25 | 0.18 | — |
| C04 | Qwen3-4B-GGUF:Q4_K_M · text | 511 | 77 | 38.68 | 0.30 | 0.35 | 0.43 | 0.38 | 0.10 | — |
| C06 | Qwen3-VL-2B-Instruct-GGUF:Q4_K_M · text | 72 | 19 | 40.45 | 0.31 | 0.38 | 0.44 | 0.40 | 0.11 | — |
| C07 | Qwen3-VL-2B-Instruct-GGUF:Q4_K_M · text+image | 346 | 155 | 44.26 | 0.37 | 0.39 | 0.50 | 0.45 | 0.07 | — |
| C09 | Llama-3.2-3B-Instruct-GGUF:Q4_K_M · text | 466 | 122 | 32.60 | 0.27 | 0.27 | 0.39 | 0.29 | 0.13 | — |
| C10 | Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M · text | 77 | 5 | 36.10 | 0.28 | 0.31 | 0.40 | 0.35 | 0.14 | — |
| C11 | Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M · text+image | 425 | 62 | 37.75 | 0.33 | 0.30 | 0.43 | 0.37 | 0.11 | — |
| C16 | Qwen3-0.6B-GGUF:Q4_K_M · text | 97 | 0 | 12.80 | 0.13 | 0.05 | 0.18 | 0.08 | 0.19 | — |
| C26 | SmolLM2-135M-Instruct-GGUF:Q4_K_M · text | 121 | 0 | 11.21 | 0.10 | 0.08 | 0.14 | 0.08 | 0.31 | — |
| C27 | SmolLM2-360M-Instruct-GGUF:Q4_K_M · text | 173 | 0 | 11.14 | 0.08 | 0.07 | 0.12 | 0.08 | 0.40 | — |
| C28 | gemma-3-270m-it-qat-GGUF:Q4_K_M · text | 181 | 0 | 11.67 | 0.09 | 0.06 | 0.14 | 0.09 | 0.41 | — |
| C38 | gpt-5-nano · text | 71 | 10 | 48.05 | 0.32 | 0.56 | 0.46 | 0.50 | 0.12 | — |
| C39 | gpt-5-nano · text+image | 314 | 194 | 52.62 | 0.39 | 0.57 | 0.52 | 0.55 | 0.12 | — |
| C40 | gpt-5.4 · text | 475 | 114 | 80.13 | 0.75 | 0.81 | 0.81 | 0.85 | 0.02 | — |
| C43 | gpt-5.4-nano · text | 39 | 49 | 63.46 | 0.47 | 0.70 | 0.59 | 0.67 | 0.07 | — |
| C44 | gpt-5.4-nano · text+image | 421 | 87 | 69.04 | 0.59 | 0.73 | 0.69 | 0.73 | 0.05 | — |

## Reference · gpt-5.5 · R03

GPT-5.4 text+image is a **reference-model control**, not an independent candidate result: comparison against its own silver labels explains its near-perfect agreement. The mixed first-pass run is split by each result's actual judge model.

| ID | Configuration | N ok | Failed | Final | Faithful | Coverage | Precision | Useful | Noise | Hallucination |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C02 | Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M · text | 538 | 0 | 9.32 | 0.14 | 0.07 | 0.11 | 0.07 | 0.38 | — |
| C16 | Qwen3-0.6B-GGUF:Q4_K_M · text | 491 | 0 | 15.65 | 0.31 | 0.08 | 0.24 | 0.10 | 0.26 | — |
| C26 | SmolLM2-135M-Instruct-GGUF:Q4_K_M · text | 469 | 0 | 13.37 | 0.20 | 0.10 | 0.15 | 0.09 | 0.35 | — |
| C27 | SmolLM2-360M-Instruct-GGUF:Q4_K_M · text | 411 | 0 | 9.81 | 0.13 | 0.08 | 0.11 | 0.07 | 0.52 | — |
| C28 | gemma-3-270m-it-qat-GGUF:Q4_K_M · text | 393 | 0 | 12.49 | 0.18 | 0.09 | 0.16 | 0.09 | 0.51 | — |

## Reference · gpt-5.4-mini · R05

GPT-5.4 text+image is a **reference-model control**, not an independent candidate result: comparison against its own silver labels explains its near-perfect agreement. The mixed first-pass run is split by each result's actual judge model.

| ID | Configuration | N ok | Failed | Final | Faithful | Coverage | Precision | Useful | Noise | Hallucination |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | Qwen3-1.7B-GGUF:Q4_K_M · text | 588 | 0 | 20.30 | 0.26 | 0.17 | 0.34 | 0.19 | 0.51 | — |
| C02 | Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M · text | 588 | 0 | 4.49 | 0.15 | 0.03 | 0.10 | 0.04 | 0.70 | — |
| C03 | Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M · text | 588 | 0 | 20.33 | 0.24 | 0.17 | 0.32 | 0.20 | 0.55 | — |
| C04 | Qwen3-4B-GGUF:Q4_K_M · text | 588 | 0 | 32.02 | 0.34 | 0.28 | 0.43 | 0.32 | 0.42 | — |
| C06 | Qwen3-VL-2B-Instruct-GGUF:Q4_K_M · text | 91 | 0 | 32.24 | 0.34 | 0.28 | 0.43 | 0.32 | 0.42 | — |
| C07 | Qwen3-VL-2B-Instruct-GGUF:Q4_K_M · text+image | 501 | 0 | 39.05 | 0.41 | 0.34 | 0.50 | 0.39 | 0.31 | — |
| C08 | Qwen3.5-4B-Q4_K_M+generic_v8 · text | 565 | 0 | 43.74 | 0.45 | 0.40 | 0.53 | 0.44 | 0.31 | — |
| C09 | Llama-3.2-3B-Instruct-GGUF:Q4_K_M · text | 588 | 0 | 23.62 | 0.31 | 0.19 | 0.38 | 0.22 | 0.45 | — |
| C10 | Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M · text | 82 | 0 | 27.30 | 0.29 | 0.23 | 0.36 | 0.27 | 0.50 | — |
| C11 | Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M · text+image | 487 | 0 | 30.70 | 0.35 | 0.25 | 0.42 | 0.30 | 0.41 | — |
| C12 | Qwen3.6-27B-MTP-Q4_K_M-Q8nextn-GGUF:Q4_K_M · text | 588 | 0 | 55.45 | 0.58 | 0.50 | 0.64 | 0.56 | 0.24 | — |
| C13 | Qwen3.6-35B-A3B-MTP-IMAT-Q4_K_M-Q8nextn-GGUF:Q4_K_M · text | 588 | 0 | 50.31 | 0.53 | 0.46 | 0.60 | 0.50 | 0.27 | — |
| C14 | MiniCPM5-1B-GGUF:F16 · text | 565 | 0 | 6.05 | 0.15 | 0.04 | 0.12 | 0.05 | 0.57 | — |
| C16 | Qwen3-0.6B-GGUF:Q4_K_M · text | 588 | 0 | 6.07 | 0.12 | 0.04 | 0.12 | 0.05 | 0.52 | — |
| C17 | Qwen3.5-0.8B-GGUF:Q4_K_M · text | 585 | 0 | 6.64 | 0.13 | 0.05 | 0.12 | 0.05 | 0.61 | — |
| C18 | Qwen3.5-0.8B-GGUF:Q4_K_M · text+image | 448 | 0 | 25.68 | 0.29 | 0.22 | 0.37 | 0.25 | 0.47 | — |
| C19 | Qwen3.5-0.8B-GGUF:Q4_K_M+generic_prompt_v1 · text | 565 | 0 | 24.93 | 0.26 | 0.22 | 0.34 | 0.25 | 0.51 | — |
| C20 | Qwen3.5-4B-GGUF:Q4_K_M · text | 586 | 0 | 39.73 | 0.41 | 0.37 | 0.50 | 0.40 | 0.35 | — |
| C21 | Qwen3.5-4B-GGUF:Q4_K_M · text+image | 503 | 0 | 44.13 | 0.45 | 0.39 | 0.53 | 0.44 | 0.31 | — |
| C22 | Qwen3.5-9B-GGUF:UD-IQ2_M · text | 588 | 0 | 35.80 | 0.37 | 0.33 | 0.47 | 0.36 | 0.36 | — |
| C23 | Qwen3.5-9B-GGUF:UD-IQ2_M · text+image | 486 | 0 | 40.18 | 0.45 | 0.35 | 0.52 | 0.40 | 0.28 | — |
| C26 | SmolLM2-135M-Instruct-GGUF:Q4_K_M · text | 590 | 0 | 5.39 | 0.13 | 0.04 | 0.12 | 0.04 | 0.72 | — |
| C27 | SmolLM2-360M-Instruct-GGUF:Q4_K_M · text | 584 | 0 | 4.71 | 0.05 | 0.04 | 0.09 | 0.04 | 0.86 | — |
| C28 | gemma-3-270m-it-qat-GGUF:Q4_K_M · text | 574 | 0 | 5.09 | 0.07 | 0.03 | 0.10 | 0.04 | 0.84 | — |
| C30 | LFM2.5-350M-MLX-8bit+minimal_summary_v3_repaired · text | 565 | 0 | 14.07 | 0.29 | 0.09 | 0.33 | 0.11 | 0.56 | — |
| C31 | LFM2.5-8B-A1B-MLX-8bit · text | 565 | 0 | 18.78 | 0.35 | 0.15 | 0.33 | 0.17 | 0.42 | — |
| C32 | gemma-4-31B-it-OptiQ-4bit · text | 588 | 0 | 51.74 | 0.58 | 0.46 | 0.62 | 0.50 | 0.25 | — |
| C33 | MiniCPM5-1B-MLX · text | 588 | 0 | 13.43 | 0.13 | 0.13 | 0.18 | 0.13 | 0.75 | — |
| C34 | Holo2-8B-bf16 · text | 588 | 0 | 35.27 | 0.38 | 0.30 | 0.47 | 0.35 | 0.38 | — |
| C35 | Qwen3-VL-32B-Thinking-5bit · text | 588 | 0 | 42.63 | 0.48 | 0.38 | 0.55 | 0.42 | 0.31 | — |
| C37 | Qwen3-VL-8B-Instruct-8bit · text | 587 | 0 | 37.86 | 0.44 | 0.33 | 0.51 | 0.37 | 0.34 | — |
| C38 | gpt-5-nano · text | 588 | 0 | 47.79 | 0.46 | 0.47 | 0.53 | 0.49 | 0.35 | — |
| C40 | gpt-5.4 · text | 589 | 0 | 78.38 | 0.79 | 0.77 | 0.82 | 0.80 | 0.12 | — |
| C41 | gpt-5.4 · text+image **control** | 506 | 0 | 99.91 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | — |
| C42 | gpt-5.4-mini · text | 588 | 0 | 69.69 | 0.70 | 0.67 | 0.75 | 0.71 | 0.17 | — |

## Source Grounded · gpt-5.4-mini · R01

| ID | Configuration | N ok | Failed | Final | Faithful | Coverage | Precision | Useful | Noise | Hallucination |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | Qwen3-1.7B-GGUF:Q4_K_M · text | 588 | 0 | 44.97 | 0.54 | 0.43 | 0.56 | 0.43 | 0.45 | 0.41 |
| C02 | Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M · text | 588 | 0 | 19.77 | 0.28 | 0.18 | 0.28 | 0.18 | 0.72 | 0.63 |
| C03 | Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M · text | 588 | 0 | 47.97 | 0.56 | 0.46 | 0.58 | 0.50 | 0.44 | 0.39 |
| C04 | Qwen3-4B-GGUF:Q4_K_M · text | 588 | 0 | 60.50 | 0.67 | 0.61 | 0.68 | 0.62 | 0.31 | 0.30 |
| C06 | Qwen3-VL-2B-Instruct-GGUF:Q4_K_M · text | 91 | 0 | 83.13 | 0.86 | 0.82 | 0.87 | 0.85 | 0.13 | 0.12 |
| C07 | Qwen3-VL-2B-Instruct-GGUF:Q4_K_M · text+image | 501 | 0 | 59.14 | 0.61 | 0.60 | 0.62 | 0.64 | 0.36 | 0.37 |
| C09 | Llama-3.2-3B-Instruct-GGUF:Q4_K_M · text | 588 | 0 | 52.05 | 0.59 | 0.49 | 0.60 | 0.56 | 0.38 | 0.37 |
| C10 | Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M · text | 82 | 0 | 79.46 | 0.85 | 0.77 | 0.86 | 0.82 | 0.14 | 0.13 |
| C11 | Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M · text+image | 487 | 0 | 54.98 | 0.57 | 0.52 | 0.58 | 0.60 | 0.39 | 0.39 |
| C16 | Qwen3-0.6B-GGUF:Q4_K_M · text | 588 | 0 | 20.09 | 0.30 | 0.17 | 0.30 | 0.18 | 0.69 | 0.58 |
| C26 | SmolLM2-135M-Instruct-GGUF:Q4_K_M · text | 590 | 0 | 17.09 | 0.29 | 0.17 | 0.29 | 0.14 | 0.75 | 0.63 |
| C27 | SmolLM2-360M-Instruct-GGUF:Q4_K_M · text | 584 | 0 | 18.55 | 0.23 | 0.19 | 0.23 | 0.16 | 0.82 | 0.72 |
| C28 | gemma-3-270m-it-qat-GGUF:Q4_K_M · text | 574 | 0 | 16.77 | 0.22 | 0.18 | 0.22 | 0.16 | 0.83 | 0.74 |
| C31 | LFM2.5-8B-A1B-MLX-8bit · text | 565 | 0 | 40.54 | 0.57 | 0.35 | 0.56 | 0.37 | 0.40 | 0.37 |
| C40 | gpt-5.4 · text | 589 | 0 | 80.07 | 0.81 | 0.86 | 0.81 | 0.82 | 0.18 | 0.18 |
| C41 | gpt-5.4 · text+image | 506 | 0 | 79.80 | 0.80 | 0.85 | 0.80 | 0.81 | 0.19 | 0.19 |

## Automation · gpt-5.4-mini · R02

These scores describe inferred workflow opportunities, **not summary accuracy or demonstrated time savings**. Two historical cohorts overlap; do not sum them as independent tasks. Behavioral and mental-state outputs are excluded from the public data.

| ID | Configuration | N ok | Failed | Final | Automation | AI delegation | Shortcuts | Repetition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | Qwen3-1.7B-GGUF:Q4_K_M · text | 588 | 0 | 42.70 | 0.50 | 0.48 | 0.47 | 0.54 |
| C02 | Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M · text | 588 | 0 | 39.06 | 0.46 | 0.45 | 0.42 | 0.52 |
| C03 | Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M · text | 588 | 0 | 43.15 | 0.50 | 0.48 | 0.47 | 0.54 |
| C04 | Qwen3-4B-GGUF:Q4_K_M · text | 588 | 0 | 45.02 | 0.53 | 0.50 | 0.49 | 0.57 |
| C06 | Qwen3-VL-2B-Instruct-GGUF:Q4_K_M · text | 91 | 0 | 52.60 | 0.59 | 0.61 | 0.50 | 0.50 |
| C07 | Qwen3-VL-2B-Instruct-GGUF:Q4_K_M · text+image | 501 | 0 | 44.68 | 0.52 | 0.53 | 0.46 | 0.53 |
| C09 | Llama-3.2-3B-Instruct-GGUF:Q4_K_M · text | 588 | 0 | 43.72 | 0.51 | 0.50 | 0.46 | 0.53 |
| C10 | Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M · text | 82 | 0 | 50.67 | 0.57 | 0.59 | 0.46 | 0.42 |
| C11 | Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M · text+image | 487 | 0 | 47.72 | 0.55 | 0.56 | 0.47 | 0.56 |
| C12 | Qwen3.6-27B-MTP-Q4_K_M-Q8nextn-GGUF:Q4_K_M · text | 588 | 0 | 45.97 | 0.54 | 0.53 | 0.50 | 0.57 |
| C13 | Qwen3.6-35B-A3B-MTP-IMAT-Q4_K_M-Q8nextn-GGUF:Q4_K_M · text | 588 | 0 | 48.56 | 0.57 | 0.55 | 0.50 | 0.56 |
| C14 | MiniCPM5-1B-GGUF:F16 · text | 565 | 0 | 44.20 | 0.52 | 0.51 | 0.46 | 0.56 |
| C16 | Qwen3-0.6B-GGUF:Q4_K_M · text | 588 | 0 | 44.76 | 0.52 | 0.50 | 0.46 | 0.54 |
| C17 | Qwen3.5-0.8B-GGUF:Q4_K_M · text | 585 | 0 | 42.56 | 0.51 | 0.50 | 0.44 | 0.53 |
| C18 | Qwen3.5-0.8B-GGUF:Q4_K_M · text+image | 448 | 0 | 45.35 | 0.53 | 0.52 | 0.46 | 0.54 |
| C19 | Qwen3.5-0.8B-GGUF:Q4_K_M+generic_prompt_v1 · text | 565 | 0 | 46.83 | 0.54 | 0.53 | 0.49 | 0.59 |
| C20 | Qwen3.5-4B-GGUF:Q4_K_M · text | 586 | 0 | 46.60 | 0.55 | 0.54 | 0.49 | 0.56 |
| C21 | Qwen3.5-4B-GGUF:Q4_K_M · text+image | 503 | 0 | 46.75 | 0.55 | 0.55 | 0.46 | 0.55 |
| C22 | Qwen3.5-9B-GGUF:UD-IQ2_M · text | 588 | 0 | 43.91 | 0.51 | 0.51 | 0.47 | 0.54 |
| C23 | Qwen3.5-9B-GGUF:UD-IQ2_M · text+image | 486 | 0 | 44.35 | 0.52 | 0.53 | 0.45 | 0.54 |
| C26 | SmolLM2-135M-Instruct-GGUF:Q4_K_M · text | 590 | 0 | 39.54 | 0.46 | 0.44 | 0.43 | 0.52 |
| C27 | SmolLM2-360M-Instruct-GGUF:Q4_K_M · text | 584 | 0 | 40.12 | 0.48 | 0.46 | 0.43 | 0.53 |
| C28 | gemma-3-270m-it-qat-GGUF:Q4_K_M · text | 574 | 0 | 43.56 | 0.51 | 0.49 | 0.46 | 0.54 |
| C30 | LFM2.5-350M-MLX-8bit+minimal_summary_v3_repaired · text | 565 | 0 | 42.12 | 0.49 | 0.48 | 0.45 | 0.54 |
| C31 | LFM2.5-8B-A1B-MLX-8bit · text | 565 | 0 | 41.95 | 0.50 | 0.48 | 0.45 | 0.54 |
| C32 | gemma-4-31B-it-OptiQ-4bit · text | 588 | 0 | 44.72 | 0.53 | 0.52 | 0.47 | 0.53 |
| C33 | MiniCPM5-1B-MLX · text | 588 | 0 | 49.70 | 0.59 | 0.56 | 0.52 | 0.61 |
| C34 | Holo2-8B-bf16 · text | 588 | 0 | 45.98 | 0.53 | 0.52 | 0.48 | 0.56 |
| C35 | Qwen3-VL-32B-Thinking-5bit · text | 588 | 0 | 43.41 | 0.52 | 0.50 | 0.49 | 0.55 |
| C37 | Qwen3-VL-8B-Instruct-8bit · text | 587 | 0 | 44.02 | 0.51 | 0.50 | 0.48 | 0.55 |
| C38 | gpt-5-nano · text | 588 | 0 | 46.34 | 0.54 | 0.54 | 0.47 | 0.54 |
| C40 | gpt-5.4 · text | 589 | 0 | 44.32 | 0.52 | 0.52 | 0.47 | 0.55 |
| C41 | gpt-5.4 · text+image | 506 | 0 | 44.32 | 0.53 | 0.55 | 0.44 | 0.53 |
| C42 | gpt-5.4-mini · text | 1,177 | 0 | 44.01 | 0.52 | 0.52 | 0.46 | 0.54 |
| C43 | gpt-5.4-nano · text | 589 | 0 | 46.49 | 0.54 | 0.54 | 0.48 | 0.55 |

## Automation · gpt-5.4-mini · R04

These scores describe inferred workflow opportunities, **not summary accuracy or demonstrated time savings**. Two historical cohorts overlap; do not sum them as independent tasks. Behavioral and mental-state outputs are excluded from the public data.

| ID | Configuration | N ok | Failed | Final | Automation | AI delegation | Shortcuts | Repetition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | Qwen3-1.7B-GGUF:Q4_K_M · text | 588 | 0 | 42.70 | 0.50 | 0.48 | 0.47 | 0.54 |
| C06 | Qwen3-VL-2B-Instruct-GGUF:Q4_K_M · text | 91 | 0 | 52.60 | 0.59 | 0.61 | 0.50 | 0.50 |
| C16 | Qwen3-0.6B-GGUF:Q4_K_M · text | 588 | 0 | 44.76 | 0.52 | 0.50 | 0.46 | 0.54 |
| C27 | SmolLM2-360M-Instruct-GGUF:Q4_K_M · text | 584 | 0 | 40.12 | 0.48 | 0.46 | 0.43 | 0.53 |
| C40 | gpt-5.4 · text | 589 | 0 | 44.32 | 0.52 | 0.52 | 0.47 | 0.55 |

[All judge scores, claim counts and denominators](../evaluations/results/judge-scores.csv) · [Per-level judge results](../evaluations/results/judge-levels.csv) · [Run totals](../evaluations/results/judge-runs.csv)
