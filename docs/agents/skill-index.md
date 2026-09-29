# Skill Index

This file is the detailed inventory of installed skills for this repo. `AGENTS.md` keeps only the bootstrap summary; this file carries the fuller index so future agents know what is available without bloating every session's top-level context.

Skills live under `.agents/skills/<skill-name>/SKILL.md`. Load the relevant skill before specialized work.

## Project and Agent Workflow

| Skill | Use when |
| --- | --- |
| `ask-matt` | Unsure which Matt Pocock skill or flow fits the situation. |
| `writing-for-agents` | Creating or editing agent-facing docs, `AGENTS.md`, instructions, skills, or context pointers. |
| `setup-matt-pocock-skills` | Setting up issue tracker, triage labels, and domain docs for the repo. |
| `handoff` | Compacting the current conversation into a handoff document for another agent. |
| `retro` | Running a retrospective on a coding session. |
| `wait-what` | Re-pitching a message that did not land. |

## Planning, Specs, and Tickets

| Skill | Use when |
| --- | --- |
| `grilling` | Stress-testing a plan or decision through structured questions. |
| `grill-me` | Sharpening a plan or design through an interview. |
| `grill-with-docs` | Grilling while also producing docs, ADRs, and glossary updates. |
| `to-questionnaire` | Turning unresolved decisions into a questionnaire. |
| `to-spec` | Turning the conversation into a spec in the issue tracker. |
| `to-tickets` | Breaking a spec or plan into implementation tickets. |
| `wayfinder` | Planning large multi-session work as a map of decision tickets. |
| `pr` | Writing a PR body. |

## Implementation and Review

| Skill | Use when |
| --- | --- |
| `implement` | Implementing work from a spec or ticket. |
| `implement-spec` | Implementing the result of `/to-spec` and `/to-tickets`. |
| `tdd` | Building features or fixes test-first. |
| `code-review` | Reviewing a branch, PR, or work-in-progress changes. |
| `diagnosing-bugs` | Debugging broken, failing, throwing, or slow behavior. |
| `prototype` | Building a throwaway prototype to answer a design question. |

## Architecture and Domain

| Skill | Use when |
| --- | --- |
| `codebase-design` | Designing modules, interfaces, seams, and testable boundaries. |
| `domain-modeling` | Updating glossary terms or ADRs while sharpening the domain model. |
| `improve-codebase-architecture` | Scanning the codebase for module deepening opportunities. |
| `triage` | Moving issues or external PRs through triage states. |

## Research and Teaching

| Skill | Use when |
| --- | --- |
| `research` | Investigating a technical topic from primary sources and writing findings. |
| `teach` | Teaching a concept or skill within this workspace. |
| `find-skills` | Discovering and installing additional public skills. |

## Configuration, Backend, and Services

| Skill | Use when |
| --- | --- |
| `python-configuration` | Designing or implementing Python configuration, environment variables, typed settings, secrets, or `pydantic-settings`. |
| `pydantic` | Modeling or validating data with Pydantic, especially constraints and model hierarchies. |
| `fastapi` | Working on FastAPI APIs, dependencies, Pydantic integration, or frontend serving. |
| `docker-compose-patterns` | Creating, modifying, or debugging Docker Compose multi-service wiring. |
| `security-and-hardening` | Handling secrets, credentials, external APIs, user input, security audits, or dependency risk. |

## Operational Helpers

| Skill | Use when |
| --- | --- |
| `wizard` | Creating an interactive shell wizard for human-only setup steps. |
| `customize-opencode` | Editing opencode config, agents, skills, plugins, MCP servers, or permission rules. |

## Project-Specific Skill Chains

## Agentic Pipeline References

Use these references when the work needs to move through an agentic lifecycle instead of a single direct edit.

### Main Flow: Idea To Ship

| Phase | Skills | Use when |
| --- | --- | --- |
| Sharpen idea | `grill-with-docs`, `grilling`, `domain-modeling` | The idea, scope, vocabulary, or trade-offs are not yet crisp. Prefer `grill-with-docs` in this repo because it can leave a paper trail in glossary and ADRs. |
| Research branch | `research` | A decision needs external facts, primary sources, library comparison, pricing, licenses, or API behavior. |
| Prototype branch | `prototype`, `handoff` | A design question needs runnable evidence, UI feel, or state-model validation before spec work. Use `handoff` when crossing session or directory boundaries. |
| Spec | `to-spec` | The conversation is ready to become a durable spec in the issue tracker. |
| Tickets | `to-tickets` | A spec needs to become tracer-bullet implementation tickets with blocking edges. |
| Implementation | `implement`, `implement-spec`, `tdd` | Build from a ticket or full spec. Use `tdd` for red-green slices. |
| Review | `code-review` | Review work against repo standards and the originating spec. |
| PR | `pr` | Write a PR body with evidence and decision framing. |
| Retrospective | `retro` | After a build or difficult session, improve the agent environment and workflow. |

### On-Ramps

| Starting point | Skills | Use when |
| --- | --- | --- |
| Raw incoming issues | `triage` | Bugs or feature requests arrive unshaped and need state, label, and agent-ready brief. |
| Broken behavior | `diagnosing-bugs` | Something fails, regresses, flakes, throws, or performs badly. |
| Foggy large effort | `wayfinder` | The destination is too large or unclear for one session; create decision tickets before spec work. |
| Codebase health | `improve-codebase-architecture`, `codebase-design` | Looking for seams, deepening opportunities, and structural improvements. |

### Phase Boundaries

| Boundary tool | Use when |
| --- | --- |
| Continue | The current context still matters and the session is inside the smart zone. |
| `handoff` | Work must move to a new session, new directory, colleague, or side task. |
| Subagent | A bounded research or exploration task can run independently and report back. |
| Compact/clear | Only at a real phase boundary when the current context is no longer needed or must be compressed. |

## Human Interaction References

Use these references when the human is part of the decision loop, has missing information, or must perform an action the agent cannot do.

| Skill | Human interaction role |
| --- | --- |
| `ask-matt` | Router for choosing the correct skill flow when the next step is unclear. |
| `grilling` | Structured interview primitive: asks the current decision frontier, facts are the agent's job, decisions are the user's. |
| `grill-me` | Stateless interview for plans or designs outside a repo context. |
| `grill-with-docs` | Stateful interview in a repo; captures resolved vocabulary and decisions in docs. |
| `to-questionnaire` | Turns unknowns into questions for another human or stakeholder to answer later. |
| `wizard` | Produces an interactive script for human-only steps such as dashboards, credentials, secrets, provisioning, or cutovers. |
| `handoff` | Writes portable context for another agent, another session, or a human collaborator. |
| `wait-what` | Re-pitches the previous explanation when it did not land. |
| `teach` | Runs a learning interaction over multiple sessions. |
| `retro` | Interviews the session outcome to improve future agent behavior and environment. |

Human validation remains required for phase changes listed in `docs/AGENT_CONTEXT.md`, especially architecture, configuration, source, security, and API decisions.

### Configuration Work

Use this chain for `.env`, `config.toml`, runtime settings, or multi-service config:

```text
python-configuration -> pydantic -> fastapi -> docker-compose-patterns -> security-and-hardening
```

Then use local process skills as needed:

```text
writing-for-agents -> codebase-design -> research -> ADR -> tdd
```

### Feature Implementation

Use this chain for substantial project features:

```text
research if needed -> to-spec -> to-tickets -> tdd -> implement -> code-review
```

### Documentation and Decisions

Use this chain for project docs, ADRs, glossary, or agent context:

```text
writing-for-agents -> domain-modeling -> grilling or grill-with-docs
```
