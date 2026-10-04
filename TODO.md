# RAG Next Plan

> Working file, non-authoritative. The sources of truth remain `docs/AGENT_CONTEXT.md`,
> `docs/MVP.md`, `docs/ARCHITECTURE.md`, `docs/DATA.md`, `docs/RAG-RUNBOOK.md`,
> `docs/adr/0006-rag-milvus-and-embeddings.md`, and the local issue specs under
> `.scratch/`.

## Current State

The RAG retrieval pipeline is implemented, smoke-tested end to end, and realigned on the full
Wikibooks corpus with hardened ingestion metadata.

Validated runtime (2026-10-04):

- Docker Compose services: MongoDB, Ollama, Milvus. Ollama runs on GPU through
  `docker-compose.gpu.yml`; `docker compose exec -T ollama ollama ps` reports `100% GPU`.
- Embeddings: Ollama `qwen3-embedding:0.6b`, digest `ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d`.
- Snapshot rebuilt with the hardened classifier and direct-child alias mapper:
  `.scratch/rag/corpus/wikibooks-snapshot` → `wb-2afb6c3916ecbab8` (hash `2afb6c39…`),
  2619 pages → 1766 accepted, 2657 chunks.
- Full-corpus collection: `chess_knowledge_fdfff4354c1c_33d349ba87d3_a608853c1518`
  (Docker Milvus, 2657 chunks, snapshot provenance recorded, validated read-only with `--no-ingest`).
- Demo collection: `chess_knowledge_fdfff4354c1c_33d349ba87d3` (Docker, 50 chunks from the 13
  curated pages, re-ingested with the hardened rules).
- `config.toml` still points `[milvus].collection` at the demo collection. Moving production to the
  full corpus is a separate validated phase (ADR + user validation).
- `POST /api/analyze-position` returns real Wikibooks `rag_context` for Ruy Lopez with source URL,
  license, `relation_to_position = current`, and no `rag_unavailable` / `milvus_unavailable` /
  `ollama_unavailable` fallback.

Hardened section intents on the full corpus (was → now): `misc` 323 → 188, new `plan` 72 and
`variation` 63, `intro` 1766, `candidate_move` 355, `history` 200, `trap` 4, `mistake` 9.

Latest verification:

```bash
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d ollama milvus mongodb
uv run pytest backend/tests
uv run python -m experiments.rag.fetch_corpus
uv run python -m backend.app.ingestion.cli --ingest-mode incremental
uv run python -m backend.app.ingestion.cli --no-ingest
uv run python -m experiments.rag.run --config experiments/rag/configs/section.json --no-ingest
```

Latest backend result:

```text
380 passed, 1 warning
```

Broad retrieval sanity baseline (`experiments/rag/run.py`, bare vector search with no retrieval
plan — corpus/embedding signal only, not a coach gate):

```text
hit_rate      1.000
precision@1   0.615
recall@k      0.536
ndcg@k        0.552
```

Weak broad cases: `sicilienne-najdorf`, `gambit-dame-refuse`, `italienne`, `gambit-roi`. In each, the
rank-1 hit is a `History` section or a same-title section from another page — both already suppressed
by the real retrieval plan. Do not tune embeddings against this harness.

Production-shaped baseline (Eval V2, full corpus, run `20261004T114631761494Z`, compared with the
pre-hardening run `20261003T221022869092Z`):

```text
coach_usable_context_rate   0.00 → 0.20
deep_descendant_pollution   0.27 → 0.00
history_pollution           0.06 → 0.00
misc_pollution              0.10 → 0.00
false_current_line          0.39 → 0.317
false_context_rate          0.84 → 0.761
current_context_hit_rate    0.60 → 0.50
precision@1 (secondary)     0.31 → 0.44
ndcg@k (secondary)          0.50 → 0.53
```

Interpretation: the metadata round removed history, misc, and deep-descendant pollution entirely, but
the coach gate is still shut. The remaining defects are intent routing, eval-metric fidelity, and a
small sibling residue — see Next Work.

Eval V2 is the gate for coach safety. `experiments/rag/run.py` stays a sanity harness.

B2 intent-routing round (run `20261004T142855670145Z`, same metric semantics as
`20261004T114631761494Z`):

```text
intent agreement            7/20 → 20/20
coach_usable_context_rate   0.20 → 0.65
false_current_line          0.317 → 0.053
false_context_rate          0.761 → 0.455
current_context_hit_rate    0.50 → 0.60
child_context_hit_rate      0.80 → 1.00
deep_descendant_pollution   0.00 → 0.00
history_pollution           0.00 → 0.00
misc_pollution              0.00 → 0.00
```

Interpretation: deterministic intent routing is now aligned with the frozen Eval V2 questions without
JEV. The next gated step remains metric fidelity (`parent_prose` and `current_node_other_prose`) and
requires explicit approval before touching `experiments/rag/eval_v2/metrics.py`.

B2 metric-fidelity round (run `20261004T143940995805Z`, **new metric semantics**: parent-node prose is
reported as `parent_prose`, same-node non-expected prose is reported as `current_node_other_prose`, and
neither counts as `false_current_line`):

```text
coach_usable_context_rate   0.65 → 0.75
false_current_line          0.053 → 0.017
false_context_rate          0.455 → 0.455
current_context_hit_rate    0.60 → 0.60
child_context_hit_rate      1.00 → 1.00
deep_descendant_pollution   0.00 → 0.00
history_pollution           0.00 → 0.00
misc_pollution              0.00 → 0.00
```

Classification counts on the metric-fidelity run: `parent_prose = 3`,
`current_node_other_prose = 34`, `false_current_line = 1`, `unrelated = 2`. Do not compare this run's
`false_current_line` or `coach_usable_context_rate` to older runs without stating the metric change.

B2 residual-prose round (run `20261004T144514370218Z`, same metric semantics as
`20261004T143940995805Z`):

```text
coach_usable_context_rate   0.75 → 0.80
false_current_line          0.017 → 0.000
false_context_rate          0.455 → 0.447
current_context_hit_rate    0.60 → 0.60
child_context_hit_rate      1.00 → 1.00
deep_descendant_pollution   0.00 → 0.00
history_pollution           0.00 → 0.00
misc_pollution              0.00 → 0.00
```

Classification counts on the residual-prose run: `parent_prose = 3`, `current_node_other_prose = 35`,
`false_current_line = 0`, `unrelated = 2`. The remaining `unrelated` documents are not sibling-line
prose: one root-page `Other moves` section for the general-principles case, and one same-node Sicilian
`Bad moves` section.

## Active Compromise

The live API currently needs a safe ECO fallback because raw-corpus ingestion can produce chunks with
`opening_node_id = None`.

Current safeguard:

- Node-filtered retrieval remains the primary path.
- If no node-mapped chunks are found, retrieval falls back to ECO-filtered prose.
- For raw ECO fallback, only section `0` is accepted as current prose.
- Unmapped History, Berlin, and other subsections are suppressed by default.

This keeps the demo useful, but it is not the final target. The target is true tree-constrained
retrieval using `opening_node_id` metadata.

## Next Work

Completed in the metadata-hardening round (`.scratch/rag-metadata-hardening/`, all issues resolved):
rule-vs-JEV classification bench, `OpeningTree` mapping in the raw ingestion path, deterministic
section-classification rules, clean re-ingest, eval/API smoke rerun, and the optional `question`
field on `AnalyzePositionRequest`.

### 1. Fix Intent Routing Before Anything Else — Completed In B2

Goal: make the retrieval plan match the question's intent. This is the largest measured defect.

Evidence from Eval V2 run `20261004T114631761494Z`: the rule router disagrees with the dataset
intent on 14 of 20 cases, mostly through the `conservative_default` → `explain_current_position`
path. Consequences: no history bucket for history questions (3 `current_context_hit` regressions), no
children bucket for next-move questions (lost `child_context_hit`), no candidate bucket for
specific-candidate questions.

Tasks:

- Inspect the frozen questions for the mismatching cases and classify each as router gap vs ambiguous
  phrasing.
- Tighten deterministic rules for `ask_history`, `ask_trap`, `ask_next_moves`, and
  `ask_specific_candidate`; keep `conservative_default` for genuinely unclear input.
- Keep JEV as the optional primary classifier behind `IntentRouter` with rule fallback; JEV must not
  persist metadata.
- Add router tests over the frozen Eval V2 question set (agreement rate, not per-case hardcoding).

Acceptance:

- Eval V2 intent agreement improves from 6/20 without regressing the 6 already correct.
- `current_context_hit_rate` recovers to at least 0.60.
- `child_context_hit_rate` stays at or above 0.80.

### 2. Make The Eval Metrics Model `relation_to_position` — Completed In B2

Goal: stop scoring the plan's own parent context as fabrication.

Evidence: 11 of the 17 `false_current_line` docs are the parent bucket the plan retrieved on purpose
(`relation_to_position = parent`). A further 34 docs are labeled `unrelated` because they sit on the
correct node but are not the exact section frozen in `expected_context.current_prose`.

Tasks:

- Add a `parent_prose` label for chunks whose node is the case's parent node; exclude it from
  `false_current_line`.
- Report same-node non-expected prose as its own label (`current_node_other_prose`) so
  `false_context_rate` distinguishes "wrong line" from "right line, other section".
- Re-baseline Eval V2 after the metric change and record both numbers; do not compare across the
  metric change without saying so.

Acceptance:

- Label semantics are documented in `experiments/rag/eval_v2/metrics.py` and covered by tests.
- A parent-bucket document is never counted as a false current line.
- The report still counts true sibling/unrelated prose as pollution.

### 3. Remove Residual Sibling Pollution — Completed In B2

Goal: eliminate the remaining prose from sibling lines.

Evidence: 6 retrieved docs carry an `opening_node_id` outside the current node, its children, and its
parent, with `intro`/`plan`/`candidate_move` intent.

Tasks:

- Trace those docs to their bucket (current vs children vs parent) and fix node scope or exclusion.
- Re-run Eval V2 and confirm the residue reaches zero without shrinking `current_context_hit_rate`.

Acceptance:

- No sibling-prose document is returned for `explain_current_position` plans.
- `deep_descendant_pollution` and `history_pollution` stay at 0.00.

### 4. Build The Conservative CoachService

Goal: generate coach explanations from structured, source-constrained context.

Do not start this before items 1-3 are validated, and record the gate decision first: Eval V2's
`coach_usable_context_rate` is all-or-nothing (any pollution disqualifies a case). Decide with fresh
numbers whether a secondary safe-subset metric (only `false_current_line`, `deep_descendant`,
child-as-current disqualify) is also needed.

First implementation must be conservative:

- Consume the `CoachContext` contract, partitioned into current and child buckets at assembly time.
- Current passages render as declarative prose; child passages only inside a conditional frame
  (`si les Noirs jouent ...Nf6`).
- Deterministic post-check: no child passage inside a current claim, no unsourced claim (source,
  license, `relation_to_position` required per passage).
- Keep the rule-based intent fallback and a deterministic output fallback.
- Treat JEV as an optional intent classifier, never as corpus authority; never persist JEV output.
- Gate with `CoachContext` contract tests plus a small golden-response set.

## Standard Validation Sequence

Use this sequence before calling the next RAG iteration done:

```bash
docker compose config --quiet
docker compose up -d mongodb ollama milvus
docker compose exec -T ollama ollama pull qwen3-embedding:0.6b
uv run pytest backend/tests
uv run python -m experiments.rag.fetch_corpus
uv run python -m backend.app.ingestion.cli --ingest-mode incremental
uv run python -m backend.app.ingestion.cli --no-ingest
uv run python -m experiments.rag.run --config experiments/rag/configs/section.json --no-ingest
```

Full-corpus Eval V2 sequence (rebuild only when the cleaner, classifier, mapper, or opening tree
changed; each rebuild produces a new snapshot hash and therefore a new collection name):

```bash
uv run python -m experiments.rag.clean_report
uv run python -m experiments.rag.build_snapshot --force
uv run python -m backend.app.ingestion.cli \
  --snapshot-dir .scratch/rag/corpus/wikibooks-snapshot \
  --ingest-mode full
uv run python -m backend.app.ingestion.cli \
  --snapshot-dir .scratch/rag/corpus/wikibooks-snapshot \
  --no-ingest \
  --collection COLLECTION_NAME_FROM_THE_INGEST_OUTPUT
uv run python -m experiments.rag.eval_v2.retrieve --collection COLLECTION_NAME_FROM_THE_INGEST_OUTPUT
```

The Eval V2 runner refuses to score a run where any case hit `rag_store_unavailable` or where every
case retrieved zero documents.

API smoke payload:

```bash
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

```bash
curl -sS http://127.0.0.1:8000/api/analyze-position \
  -H 'Content-Type: application/json' \
  -d '{
    "fen":"r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 2 3",
    "pgn":"1. e4 e5 2. Nf3 Nc6 3. Bb5",
    "moves":["e2e4","e7e5","g1f3","b8c6","f1b5"],
    "level":"intermediaire"
  }'
```

Expected API smoke result:

- `opening.name = Ruy Lopez`.
- `rag_context[0].source = wikibooks-chess-opening-theory`.
- `rag_context[0].license_or_terms` is present.
- `rag_context[0].relation_to_position = current`.
- `fallbacks_used` does not include `rag_unavailable`, `milvus_unavailable`, or `ollama_unavailable`.

## Do Not Do Yet

- Do not build the final generative coach before intent routing and Eval V2 metrics are fixed.
- Do not point `config.toml` at the full-corpus collection before that switch has its own validated
  round with user validation.
- Do not remove a validated Milvus collection before a replacement passes smoke/eval.
- Do not make child prose current-position prose.
- Do not vectorize `lichess-org/chess-openings` TSV rows.
- Do not add LangGraph wiring before the imperative services are stable.
- Do not persist JEV-generated metadata into Milvus unless a later explicit decision makes the
  provider, model, prompt/schema, confidence gates, and fallback behavior part of the corpus manifest.
- Do not tune embeddings against `experiments/rag/run.py`; it does not run the retrieval plan.
