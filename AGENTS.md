## Agent Bootstrap

Start every session here. This file is the short index for agent context and tooling; detailed project rules live in the linked docs.

### Project context

Read `docs/AGENT_CONTEXT.md` before proposing or implementing project work. It defines the current source of truth, required docs, validation workflow, and project constraints.

For Angular UI changes or visual review, read `UI-WORKFLOW.md`. It defines the screenshot feedback loop and the repo-level capture tool under `tools/ui-capture/`.

### Skill index

Skills are installed under `.agents/skills/`. Load the relevant skill before specialized work.

For the full inventory, see `docs/agents/skill-index.md`.

For agentic pipeline flows and human interaction patterns, see `docs/agents/skill-index.md#agentic-pipeline-references` and `docs/agents/skill-index.md#human-interaction-references`.

High-priority skills for this project:

- `python-configuration`: Python settings, `.env`, `pydantic-settings`, runtime config.
- `pydantic`: Pydantic validation and modeling.
- `fastapi`: FastAPI APIs, dependencies, Pydantic integration.
- `docker-compose-patterns`: Docker Compose multi-service wiring.
- `security-and-hardening`: secrets, external APIs, credentials, hardening.
- `writing-for-agents`: writing or restructuring agent-facing docs.
- `ask-matt`: route work through the right skill flow.
- `codebase-design`: module/interface design and seams.
- `research`: source-backed technical research before ADRs.
- `tdd`: implementation with tests first.
- `to-spec` / `to-tickets`: convert decisions into tracked work.

### Configuration rule

For backend and multi-service configuration work, load `python-configuration`, `pydantic`, `fastapi`, `docker-compose-patterns`, and `security-and-hardening`.

Project rule:

- `.env` contains only secrets and environment-specific values.
- `config.toml` contains non-secret runtime parameters.
- All config is validated by Pydantic.
- Application code depends on a validated settings object, not direct file or environment reads.

## Agent skills

### Issue tracker

Issues are tracked as local markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

This repo uses the default triage label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This repo uses a single-context domain docs layout. See `docs/agents/domain.md`.
