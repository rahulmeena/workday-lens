# A memory of your work, for the agents you choose

Workday Lens turns everyday activity into a lasting record of what you worked on, the projects involved, and how tasks fit together. The product direction is a private memory layer that can supply useful context to the AI assistants and agents you choose.

For example, a selected project summary could help an agent pick up an unfinished task, prepare a handoff, or explain the work behind a daily recap. These are intended integration use cases; the desktop app currently focuses on collecting, interpreting and displaying work context.

## Available today

The macOS development branch (`main`) stores structured activity and hierarchical summaries locally. Its API exposes timestamps, headlines, summaries, goals, projects and links through the hierarchy. Developers can retrieve selected records and build their own context-sharing workflow around them.

| Existing local endpoint | Context available |
| --- | --- |
| `GET /api/v1/activity/dashboard?day=YYYY-MM-DD` | Daily story and activity segments, including goals, projects and next steps |
| `GET /api/v1/activity/rollups?level=1h&day=YYYY-MM-DD` | Structured summaries at a selected hierarchy level and date |
| `GET /api/v1/activity/rollups/{rollup_id}/children` | The summaries or activity windows behind a parent summary |

See the [endpoint implementation](../backend/app/api/v1/endpoints/activity.py), [response schemas](../backend/app/schemas.py) and [architecture](architecture.md#hierarchical-context). The running backend exposes its API documentation at `/docs`; the [synthetic demo](development.md#synthetic-demo) provides fictional data for exploring it.

## Planned integrations

Ready-made Claude/Codex connectors, an MCP interface, portable context exports, and project/time/field sharing controls are [roadmap work](roadmap.md#memory-for-your-agents). They are not included as turnkey integrations in the current release. The goal is to keep the memory useful across agent providers while letting the user choose the context each agent receives.

## Context you can inspect

Summaries are model inferences from incomplete evidence. An integration should preserve time ranges, model provenance and the path back to supporting activity so a receiving agent can distinguish observations from interpretations. The [evaluation report](evaluation.md) measures aspects of summary fidelity; downstream agent-memory usefulness still needs its own evaluation.

Data is stored locally. Cloud inference and any context you choose to pass to an external assistant have separate data flows. The local API is intended for loopback use and currently has no authentication or per-agent access controls. Read [model support](model-support.md) and [privacy](privacy.md) when choosing a workflow.
