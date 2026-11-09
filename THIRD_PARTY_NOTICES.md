# Third-party notices

Original Workday Lens code is copyright Rahul Meena and licensed under GNU GPL v3.0. Upstream components retain their licenses and copyrights.

## Windows capture

- **NVDA**, NV Access and contributors: [source](https://github.com/nvaccess/nvda), [license/notices](https://github.com/nvaccess/nvda/blob/master/copying.txt). Windows packaging uses NVDA 2025.3.3. Public source snapshots omit the installer binary; obtain the matching upstream runtime when building.
- **Speech Logger**, Luke Davis, James Scholes, and contributors: [source](https://github.com/opensourcesys/speechLogger). Modified source headers specify GPL version 2 or later. Workday Lens adds timestamped capture, mouse events, and optional screenshots. Windows branches include editable add-on source, upstream notices, and GPL v2 text.

## Dependencies

Python/JavaScript dependencies are declared in requirements files and the frontend lockfile. Each retains its upstream license. Windows binaries also bundle runtime components whose applicable notices must accompany redistribution.

Local inference uses [llama.cpp](https://github.com/ggml-org/llama.cpp), licensed under MIT. The configured [Qwen GGUF model](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF) is downloaded separately and has its own license/model metadata. No model weights are included.

This public source release is separate from historical binaries on navya.ai. New binary distributions must include the licenses and corresponding source required by every bundled component.
