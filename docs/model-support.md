# Model support: application and evaluation

Workday Lens is GPL-3.0 software. Its code license is separate from the model provider: an open-source application can use a proprietary API, locally available weights, or a synthetic demo. “Open-weight” describes the local evaluation group without claiming that all model licenses have identical terms.

## Windows beta

The published `windows-beta` and `windows-arm64-beta` source branches use the OpenAI API for real inference. Users supply their own key. The backend also has a fake mode for development; fake mode is not a local language model.

Neither Windows beta branch contains the later local Qwen provider. The maintainer has installed and tested the Windows beta. The website's historical installer has not been established as a byte-for-byte build of these source snapshots; see [provenance](versions.md).

Code: [Windows OpenAI client](https://github.com/rahulmeena/workday-lens/blob/windows-beta/backend/app/services/llm.py), [Windows setup](https://github.com/rahulmeena/workday-lens/blob/windows-beta/backend/app/api/v1/endpoints/setup.py), [ARM64 client](https://github.com/rahulmeena/workday-lens/blob/windows-arm64-beta/backend/app/services/llm.py).

## macOS development

`main` implements two real providers: `openai` and `local_qwen35_4b`. The local provider runs **Qwen3.5-4B, GGUF Q4_K_M, with the `generic_v8` prompt**, through a locally managed llama.cpp server. It handles activity windows, hierarchical rollups, and day stories. Gantt ranking and composition use deterministic fallbacks when local Qwen is selected, so provider behavior is not identical.

The integration is present in the source and the macOS development app has been used by the maintainer. This is not a packaged, externally validated macOS release. Runtime/model setup, sufficient memory and disk space are needed; fresh-machine installation and a signed/notarized distribution remain release work.

Code: [provider configuration](../backend/app/core/config.py), [provider dispatch and fallbacks](../backend/app/services/llm.py), [local Qwen runtime](../backend/app/services/local_qwen.py), [setup API](../backend/app/api/v1/endpoints/setup.py). Follow the [development guide](development.md) for source setup.

## Evaluation coverage

The [evaluation archive](evaluation.md) covers 46 configurations spanning 25 local/open-weight and 4 proprietary candidate identities. Models were exercised through llama.cpp, MLX, MLX-VLM, Transformers and OpenAI. This research coverage is broader than the application's provider selection.

The [grouped comparison](evaluation-comparison.md) separates open-weight/local and proprietary candidates. It reports observed scores for a stated run, modality and rubric; it does not certify every candidate as deployable in Workday Lens. Reference agreement and source-grounded quality answer different questions, and their scores should not be merged. Judge models are also separate from candidate models.

## Planned support

The goal is a documented choice between cloud APIs and local inference across both platforms. Next work includes Windows local-model integration, broader provider/model selection, consistent feature behavior, fresh-machine setup, and matched evaluations before recommending defaults. These are [planned contributions](roadmap.md#inference-and-model-choice), not existing Windows features.

With OpenAI selected, captured text and selected summaries leave the machine for inference. With local Qwen selected, inference is local after runtime/model downloads. [Privacy details](privacy.md).
