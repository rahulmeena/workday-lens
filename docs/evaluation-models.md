# Model inventory and runtime results

[Evaluation overview](evaluation.md) · [Judge scores](evaluation-judges.md) · [Runtime and inventory](evaluation-models.md) · [Prompt experiments](evaluation-prompts.md)

Generated from the [public aggregate CSV](../evaluations/results/configurations.csv). All 46 normalized configurations are included, including failed and partial runs. `N` counts persisted generation records, including reference/teacher generations; it is not a count of independent examples or API attempts.

Runtime groups can combine sessions on different machines/settings. Latency is recorded wall-clock generation latency, not decode throughput. Mean/median/p95 use successful records with positive recorded latency; missing timing stays blank. Do not read these as a hardware-controlled speed leaderboard.

## Inventory and reliability

| ID | Recorded model / variant | Runtime | Mode | N | Succeeded | Failed | Other | Schema valid % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | `QuantFactory/Qwen3-1.7B-GGUF:Q4_K_M` | llama_cpp | text | 588 | 588 | 0 | 0 | 100.0 |
| C02 | `Qwen/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M` | llama_cpp | text | 588 | 588 | 0 | 0 | 100.0 |
| C03 | `Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M` | llama_cpp | text | 588 | 588 | 0 | 0 | 100.0 |
| C04 | `Qwen/Qwen3-4B-GGUF:Q4_K_M` | llama_cpp | text | 588 | 588 | 0 | 0 | 100.0 |
| C05 | `Qwen/Qwen3-8B-GGUF:Q4_K_M` | llama_cpp | text | 200 | 0 | 200 | 0 | 0.0 |
| C06 | `Qwen/Qwen3-VL-2B-Instruct-GGUF:Q4_K_M` | llama_cpp | text | 91 | 91 | 0 | 0 | 100.0 |
| C07 | `Qwen/Qwen3-VL-2B-Instruct-GGUF:Q4_K_M` | llama_cpp | text+image | 531 | 501 | 30 | 0 | 94.4 |
| C08 | `Qwen3.5-4B-Q4_K_M+generic_v8` | llama_cpp | text | 590 | 590 | 0 | 0 | 100.0 |
| C09 | `bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M` | llama_cpp | text | 588 | 588 | 0 | 0 | 100.0 |
| C10 | `ggml-org/Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M` | llama_cpp | text | 82 | 82 | 0 | 0 | 100.0 |
| C11 | `ggml-org/Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M` | llama_cpp | text+image | 505 | 487 | 18 | 0 | 96.4 |
| C12 | `localweights/Qwen3.6-27B-MTP-Q4_K_M-Q8nextn-GGUF:Q4_K_M` | llama_cpp | text | 593 | 593 | 0 | 0 | 100.0 |
| C13 | `localweights/Qwen3.6-35B-A3B-MTP-IMAT-Q4_K_M-Q8nextn-GGUF:Q4_K_M` | llama_cpp | text | 598 | 598 | 0 | 0 | 100.0 |
| C14 | `openbmb/MiniCPM5-1B-GGUF:F16` | llama_cpp | text | 594 | 594 | 0 | 0 | 100.0 |
| C15 | `sinimiini/HRM-Text-1B-GGUF:Q5_K_M` | llama_cpp | text | 9 | 5 | 4 | 0 | 55.6 |
| C16 | `unsloth/Qwen3-0.6B-GGUF:Q4_K_M` | llama_cpp | text | 594 | 594 | 0 | 0 | 100.0 |
| C17 | `unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M` | llama_cpp | text | 675 | 672 | 3 | 0 | 99.6 |
| C18 | `unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M` | llama_cpp | text+image | 575 | 450 | 125 | 0 | 78.3 |
| C19 | `unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M+generic_prompt_v1` | llama_cpp | text | 590 | 590 | 0 | 0 | 100.0 |
| C20 | `unsloth/Qwen3.5-4B-GGUF:Q4_K_M` | llama_cpp | text | 668 | 667 | 1 | 0 | 99.9 |
| C21 | `unsloth/Qwen3.5-4B-GGUF:Q4_K_M` | llama_cpp | text+image | 506 | 503 | 3 | 0 | 99.4 |
| C22 | `unsloth/Qwen3.5-9B-GGUF:UD-IQ2_M` | llama_cpp | text | 672 | 672 | 0 | 0 | 100.0 |
| C23 | `unsloth/Qwen3.5-9B-GGUF:UD-IQ2_M` | llama_cpp | text+image | 507 | 488 | 19 | 0 | 96.3 |
| C24 | `unsloth/Qwen3.5-9B-MTP-GGUF:UD-IQ2_M` | llama_cpp | text | 350 | 0 | 350 | 0 | 0.0 |
| C25 | `unsloth/Qwen3.5-9B-MTP-GGUF:UD-IQ2_M` | llama_cpp | text+image | 199 | 0 | 199 | 0 | 0.0 |
| C26 | `unsloth/SmolLM2-135M-Instruct-GGUF:Q4_K_M` | llama_cpp | text | 594 | 590 | 4 | 0 | 99.3 |
| C27 | `unsloth/SmolLM2-360M-Instruct-GGUF:Q4_K_M` | llama_cpp | text | 588 | 584 | 4 | 0 | 99.3 |
| C28 | `unsloth/gemma-3-270m-it-qat-GGUF:Q4_K_M` | llama_cpp | text | 588 | 574 | 14 | 0 | 97.6 |
| C29 | `LiquidAI/LFM2.5-350M-MLX-8bit+minimal_summary_v3` | mlx | text | 5 | 5 | 0 | 0 | 100.0 |
| C30 | `LiquidAI/LFM2.5-350M-MLX-8bit+minimal_summary_v3_repaired` | mlx | text | 595 | 595 | 0 | 0 | 100.0 |
| C31 | `LiquidAI/LFM2.5-8B-A1B-MLX-8bit` | mlx | text | 722 | 709 | 13 | 0 | 98.2 |
| C32 | `mlx-community/gemma-4-31B-it-OptiQ-4bit` | mlx | text | 588 | 588 | 0 | 0 | 100.0 |
| C33 | `openbmb/MiniCPM5-1B-MLX` | mlx | text | 596 | 592 | 4 | 0 | 99.3 |
| C34 | `mlx-community/Holo2-8B-bf16` | mlx_vlm | text | 588 | 588 | 0 | 0 | 100.0 |
| C35 | `mlx-community/Qwen3-VL-32B-Thinking-5bit` | mlx_vlm | text | 588 | 588 | 0 | 0 | 100.0 |
| C36 | `mlx-community/Qwen3-VL-8B-Instruct-5bit` | mlx_vlm | text | 1 | 0 | 1 | 0 | 0.0 |
| C37 | `mlx-community/Qwen3-VL-8B-Instruct-8bit` | mlx_vlm | text | 588 | 587 | 1 | 0 | 99.8 |
| C38 | `gpt-5-nano` | openai | text | 973 | 972 | 1 | 0 | 99.9 |
| C39 | `gpt-5-nano` | openai | text+image | 2,588 | 2,584 | 4 | 0 | 99.8 |
| C40 | `gpt-5.4` | openai | text | 672 | 672 | 0 | 0 | 100.0 |
| C41 | `gpt-5.4` | openai | text+image | 506 | 506 | 0 | 0 | 100.0 |
| C42 | `gpt-5.4-mini` | openai | text | 1,177 | 1,177 | 0 | 0 | 100.0 |
| C43 | `gpt-5.4-nano` | openai | text | 1,036 | 1,035 | 0 | 1 | 99.9 |
| C44 | `gpt-5.4-nano` | openai | text+image | 2,588 | 2,584 | 4 | 0 | 99.8 |
| C45 | `sapientinc/HRM-Text-1B` | transformers | text | 11 | 6 | 5 | 0 | 54.5 |
| C46 | `unsloth/gemma-3-270m-it` | transformers | text | 5 | 1 | 4 | 0 | 20.0 |

One HRM local-file alias was merged into its Hugging Face identifier. GGUF/MLX packaging, quantization and prompt variants collapse to base identities for the headline count; the configuration rows retain those distinctions. Qwen3-8B had 200 failed records and no successful generation. The other 24 local identities had at least one success; this includes small smoke runs, not just full benchmark runs.

## Recorded latency and token use

| ID | Timed successes | Mean s | Median s | p95 s | Mean input tokens | Mean output tokens | Recorded tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | 588 | 5.70 | 5.05 | 8.36 | 2667 | 250 | 1,715,142 |
| C02 | 588 | 2.92 | 2.72 | 3.94 | 2669 | 173 | 1,671,126 |
| C03 | 588 | 5.62 | 5.49 | 7.80 | 2677 | 333 | 1,769,567 |
| C04 | 588 | 11.17 | 9.72 | 16.72 | 2678 | 323 | 1,765,037 |
| C05 | 0 | — | — | — | — | — | 0 |
| C06 | 91 | 2.73 | 2.78 | 3.27 | 640 | 250 | 80,949 |
| C07 | 501 | 9.98 | 9.55 | 16.32 | 6163 | 273 | 3,397,385 |
| C08 | 590 | 11.94 | 8.95 | 29.42 | 4130 | 325 | 2,628,014 |
| C09 | 588 | 6.31 | 5.62 | 9.07 | 2243 | 199 | 1,436,144 |
| C10 | 82 | 3.93 | 3.75 | 5.23 | 653 | 244 | 73,527 |
| C11 | 487 | 19.05 | 16.62 | 34.86 | 7003 | 177 | 3,642,899 |
| C12 | 593 | 43.96 | 39.53 | 68.75 | 2858 | 262 | 1,850,194 |
| C13 | 598 | 9.66 | 8.03 | 13.71 | 2860 | 290 | 1,883,873 |
| C14 | 594 | 3.52 | 2.51 | 4.83 | 2264 | 244 | 1,489,453 |
| C15 | 5 | 8.94 | 7.46 | 13.97 | 1383 | 359 | 16,897 |
| C16 | 594 | 4.06 | 3.69 | 6.06 | 2658 | 199 | 1,697,006 |
| C17 | 672 | 5.73 | 5.03 | 11.28 | 2562 | 239 | 1,904,947 |
| C18 | 450 | 6.01 | 5.63 | 9.23 | 6322 | 247 | 3,321,620 |
| C19 | 590 | 2.45 | 1.89 | 5.50 | 3907 | 267 | 2,462,591 |
| C20 | 667 | 81.62 | 11.29 | 17.31 | 2598 | 340 | 1,959,243 |
| C21 | 503 | 15.67 | 14.06 | 25.49 | 6238 | 225 | 3,273,968 |
| C22 | 672 | 44.91 | 15.23 | 24.33 | 2595 | 323 | 1,961,115 |
| C23 | 488 | 22.85 | 21.03 | 38.00 | 6280 | 193 | 3,277,675 |
| C24 | 0 | — | — | — | — | — | 0 |
| C25 | 0 | — | — | — | — | — | 0 |
| C26 | 590 | 3.93 | 4.00 | 5.21 | 1517 | 124 | 978,053 |
| C27 | 584 | 3.28 | 3.07 | 4.65 | 2747 | 308 | 1,784,351 |
| C28 | 574 | 6.42 | 6.33 | 9.04 | 2894 | 302 | 1,862,777 |
| C29 | 5 | 0.59 | 0.27 | 2.00 | 2447 | 48 | 12,475 |
| C30 | 595 | 0.30 | 0.16 | 1.36 | 2371 | 56 | 1,444,159 |
| C31 | 709 | 15.35 | 13.30 | 27.89 | 2479 | 1767 | 3,110,134 |
| C32 | 588 | 27.98 | 23.85 | 39.07 | 2887 | 189 | 1,808,629 |
| C33 | 592 | 0.82 | 0.48 | 1.25 | 1639 | 129 | 1,056,630 |
| C34 | 588 | 23.97 | 15.91 | 61.75 | 2922 | 356 | 1,927,160 |
| C35 | 588 | 90.11 | 97.84 | 117.85 | 2922 | 889 | 2,241,094 |
| C36 | 0 | — | — | — | — | — | 0 |
| C37 | 587 | 9.60 | 8.29 | 11.64 | 2915 | 189 | 1,829,580 |
| C38 | 384 | 76.49 | 72.82 | 122.17 | 2693 | 8892 | 11,260,221 |
| C39 | 2,584 | 77.21 | 43.45 | 100.18 | 8419 | 7025 | 39,906,523 |
| C40 | 589 | 51.06 | 26.14 | 66.44 | 3417 | 2121 | 3,721,581 |
| C41 | 57 | 28.20 | 27.81 | 45.67 | 7715 | 2219 | 5,027,087 |
| C42 | 0 | — | — | — | 3732 | 2517 | 7,355,240 |
| C43 | 446 | 9.39 | 8.96 | 13.66 | 2592 | 1275 | 4,002,016 |
| C44 | 2,584 | 10.76 | 9.74 | 17.02 | 7740 | 1430 | 23,695,946 |
| C45 | 6 | 53.19 | 17.57 | 175.12 | 1694 | 327 | 21,238 |
| C46 | 1 | 9.35 | 9.35 | 9.35 | 1287 | 249 | 9,500 |

[Per-level results](../evaluations/results/generation-levels.csv) · [Recorded runtime metadata](../evaluations/results/runtime-metadata.csv) · [All stored metrics](../evaluations/results/stored-metrics.csv)

The metadata records Apple M5 Pro / 48 GB for some macOS runs. Earlier Windows runs do not have equivalent hardware metadata, so missing entries must not be inferred. Estimated cost is available only for a subset of records; it is retained in CSV as an historical estimate, not current pricing.
