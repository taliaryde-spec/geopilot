# GeoPilot repository instructions

## Living Agent documentation

Any change that adds, removes, or materially changes an Agent-related component must update both living documents in the same change:

1. `docs/AGENT_COMPONENTS.md` records what GeoPilot actually implements: component role, call path, source files, parameters, design trade-offs, experiment evidence, limitations, and an appended dated change entry.
2. `docs/AGENT_INTERVIEW_QA.md` records likely interview questions and project-specific answers. Answers must describe GeoPilot's real implementation and boundaries rather than generic definitions.

Agent-related scope includes model adapters, prompts, structured output, tool/function calling, Agent runtime, planning, guardrails, human approval, deterministic tools exposed to the Agent, execution/checkpoints, RAG, Embedding, retrieval, evaluation, memory, tracing, API/UI integration, deployment, security, and MCP.

For each meaningful iteration:

- append a dated entry to the engineering record; do not silently erase prior experiment history;
- update or append the corresponding interview questions and answers;
- include real source paths, tests, commands, metrics, and known limitations;
- distinguish implemented behavior from planned work;
- never describe a component as production-ready based only on demo data or a small evaluation set.
