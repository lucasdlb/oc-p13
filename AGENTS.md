# Agent Bootstrap

Use this file as the short entry point for work in this repository.

1. Read `docs/AGENT_CONTEXT.md` to route the task to the relevant project rules.
2. Read `docs/GLOSSARY.md` when the task involves product language, user-facing text, or domain models.
3. Use `docs/README.md` to find the authoritative document for a topic.
4. Load the relevant skill from `.agents/skills/` before specialized work; use the skill's own instructions for optional tracker setup.
5. Keep decisions in `docs/adr/` and keep generated artifacts out of source documentation.

Project-wide configuration rules:

- `.env` contains secrets and environment-specific values only.
- `config.toml` contains non-secret runtime parameters.
- Pydantic validates configuration before application code uses it.
- Application code depends on the validated settings object, not direct environment or file reads.

For Angular UI work, use `docs/runbooks/UI-WORKFLOW.md`.
