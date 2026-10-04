# Current Working Plan

> Temporary working file. Keep this short and current. Durable project rules live in
> `docs/AGENT_CONTEXT.md`, `docs/RAG-RUNBOOK.md`, `docs/adr/0006-rag-milvus-and-embeddings.md`,
> and the source/test contracts.

## Current State

- LLM coach synthesis (Plan B) is complete and validated: `LlmCoachService` is the default coach
  renderer, backed by Ollama `qwen2.5:7b-instruct`, with deterministic fallback
  `llm_coach_unavailable`.
- TypeSafe JEV integration is fixed and validated: endpoint `/v1/systemone`, real API smoke test
  returns `source="jev"` with confidence 1.0 on demo questions. The A/B experiment showed that
  keeping `typesafe.enabled = true` as the committed default regresses Eval V2 context quality,
  so the toggle is reset to `false` in `config.toml`.
- Latest backend validation: `uv run pytest backend/tests` -> `399 passed, 1 warning`.
- Full-corpus Eval V2 collection: `chess_knowledge_fdfff4354c1c_33d349ba87d3_a608853c1518`.
- Demo collection in committed `config.toml`: `chess_knowledge_fdfff4354c1c_33d349ba87d3`.

## Next Work

### 1. JEV A/B routing experiment (Plan A)

After the LLM coach synthesis is stable, run a deterministic-vs-JEV routing A/B pass on Eval V2
or a representative subset. Compare intent agreement, fallback rate, `coach_usable_context_rate`,
`false_current_line_rate`, and `false_context_rate`. See tickets in `.scratch/jev-routing-ab/issues/`.

## Accepted Eval V2 Gate

Run `20261004T170521253670Z` uses the current metric semantics (gate still holds after Plan B):

- `parent_prose`: immediate parent-node prose, not counted as `false_current_line`.
- `current_node_other_prose`: same-node prose outside the frozen expected section.
- `false_current_line`: wrong-line opening prose after excluding current, parent, allowed child,
  and deep-descendant labels.

Current gate numbers:

```text
coach_usable_context_rate   0.80
false_current_line          0.000
false_context_rate          0.447
current_context_hit_rate    0.60
child_context_hit_rate      1.00
deep_descendant_pollution   0.00
history_pollution           0.00
misc_pollution              0.00
```

Do not compare `false_current_line` or `coach_usable_context_rate` to pre-metric-fidelity runs
without stating the metric change.

## Completed

### Coach LLM synthesis (Plan B)

- Introduced `CoachService` seam; `ConservativeCoachService` remains the deterministic baseline.
- Implemented `LlmCoachService` calling Ollama on the grounded `CoachContext`.
- Fallback to deterministic template with label `llm_coach_unavailable` on error, timeout, empty
  response, missing citations, or length overflow.
- Updated ADR 0007, `docs/ARCHITECTURE.md`, `docs/RISKS.md`.
- Smoke-tested `LlmCoachService` against `p13-ollama` (French Defense, debutant) and verified
  fallback to deterministic template with `llm_coach_unavailable` when Ollama is unreachable.
- Eval V2 gate still holds on run `20261004T170521253670Z`.
- Backend tests: `399 passed, 1 warning`.

### JEV A/B routing experiment (Plan A)

- Ran deterministic-vs-JEV A/B harness on the full Eval V2 dataset
  (`experiments/rag/eval_v2/runs/ab/20261004T171526048942Z`).
- Conservative-coach decision baseline:
  - intent agreement rate: 0.75
  - JEV fallback rate: 0.05
  - deterministic intent accuracy: 1.00, JEV intent accuracy: 0.75
  - `coach_usable_context_rate` regression: -0.15 (JEV 0.65 vs deterministic 0.80)
  - `false_current_line_rate` regression: +0.20 (JEV 0.20 vs deterministic 0.00)
  - `false_context_rate` regression: +0.18 (JEV 0.63 vs deterministic 0.45)
- LLM-coach sample run (`--coach llm --limit 5`):
  `experiments/rag/eval_v2/runs/ab/20261004T175708170486Z`.
- Decision: `typesafe.enabled` reverted to `false` in `config.toml`; JEV remains opt-in via
  environment/`.env` but is not the committed default until regressions are fixed.

### Deterministic Coach API Baseline

Implemented and validated:

- Current passages render as current-position explanation.
- Child passages render only in conditional frames such as `Si les Noirs jouent ...Nf6`.
- Unsourced passages produce the deterministic safe fallback.
- Existing API fallback behavior remains stable.
- API-level golden tests cover Ruy Lopez current prose, next-move child prose, RAG failure, demo
  seed, and Lichess paths.

Validation commands:

```bash
uv run pytest backend/tests
uv run python -m experiments.rag.eval_v2.retrieve --collection chess_knowledge_fdfff4354c1c_33d349ba87d3_a608853c1518
```

Result: `399 passed, 1 warning`; Eval V2 run `20261004T150555741956Z` matches the accepted gate
materially.

## Do Not Do

- Do not point `config.toml` at the full-corpus collection without a separate validated production
  switch.
- Do not treat `experiments/rag/run.py` as the coach gate; it is a broad vector-search sanity
  harness.
- Do not make child prose current-position prose.
- Do not persist JEV-generated metadata into Milvus.
- Do not add LangGraph wiring before the imperative coach path is stable.
- Do not commit intermediate Eval V2 or broad RAG run directories unless they are accepted
  baselines.
