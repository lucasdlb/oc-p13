# Agent Context

This document routes agents through the project context. Read it first, then load only the documents required by the task. The documentation index is `docs/README.md`.

## Product

The project is a local proof of concept that helps young chess players understand opening positions. The complete demonstration path is the priority: play moves, identify the opening, show candidate moves and Lichess statistics, explain the position with grounded context, use Stockfish outside theory, and expose video or documented fallback information.

The product is a constrained hybrid coach. Deterministic code owns chess legality, source boundaries, budgets, persistence, fallbacks, and engine facts. LangGraph orchestrates stabilized services. The LLM reformulates available evidence for the selected level and must not invent facts.

## Non-negotiable stack

Angular, FastAPI, Docker Compose, Stockfish, LangGraph, MongoDB, Milvus, Lichess API, and YouTube API are part of the target deliverable. A replacement or fallback is valid only when its activation condition, demo impact, and return path are documented in `docs/ARCHITECTURE.md` or an ADR.

## Route By Task

Load only the relevant branch in addition to this file:

| Task | Read next |
| --- | --- |
| Run the application or configure a local environment | `README.md`, `config.toml`, relevant Compose/runbook files |
| Understand product scope or acceptance criteria | `docs/MVP.md` |
| Backend API, services, orchestration, or contracts | `docs/ARCHITECTURE.md`, then relevant ADRs in `docs/adr/` |
| MongoDB, Milvus, RAG, ingestion, cache, source, or license work | `docs/data/README.md`, relevant file in `docs/data/`, `docs/runbooks/RAG.md`, then ADR 0003/0005/0006 |
| Angular, layout, interaction, or visual review | `docs/UX.md`, `docs/runbooks/UI-WORKFLOW.md`, ADR 0004 |
| Coach, references, claims, or LLM behavior | ADR 0007/0008/0009/0010/0011 and `docs/runbooks/RAG.md` |
| Planning or delivery order | `docs/PLAN.md` |
| Risks or fallback behavior | `docs/RISKS.md`, then the relevant ADR |
| Product vocabulary or domain model | `docs/GLOSSARY.md` |
| Original client brief | `docs/PROJECT.md`, only when the current docs do not answer the question |

## Working Rules

- Inspect the current code and authoritative docs before proposing changes.
- Keep one source of truth for each decision; link instead of duplicating explanations.
- Research and record a decision before changing an open architectural choice.
- Major architectural, data, provider, external API, fallback, or MVP-priority changes require explicit user validation before implementation.
- Preserve source attribution, license status, and fallback visibility in product behavior.
- Validate changes with the narrowest relevant tests and record any unrun validation.

## Documentation Rules

- `README.md` is the human how-to at the repository root.
- `docs/README.md` is the documentation index.
- `docs/AGENT_CONTEXT.md` is the agent routing contract, not a complete technical manual.
- `docs/adr/` records durable structural decisions.
- Generated reports, experiment runs, screenshots, and local agent scratch belong outside source documentation and should be ignored when appropriate.
