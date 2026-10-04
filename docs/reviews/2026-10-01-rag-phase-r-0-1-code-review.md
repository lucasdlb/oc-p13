# Code review — RAG Phase R + 0 + 1

> Non-authoritative working artifact. The sources of truth remain `docs/` and
> `docs/adr/`. This review does not change any decision; findings feed the next phase.
>
> Produced with the `code-review` skill (Standards + Spec axes) run as two parallel
> reviewers, then aggregated here without merging the axes.

- **Date:** 2026-10-01
- **Fixed point:** `5102ec65a20b251a86e421feefa79b61fdec6c69` (HEAD)
- **Scope:** working tree vs HEAD, tracked changes **and** untracked new files
  (`git diff HEAD` + `git ls-files --others --exclude-standard`)
- **Review type:** read-only (no files changed, no tests rerun)
- **Spec source:** the user-approved Phase R + Phase 0 + Phase 1 plan (conversation + `TODO.md`),
  with the latest discussion on `chess-openings` used as design context.

## Overall

The implementation provides useful building blocks, but the evaluation does not yet
justify treating the RAG design as validated. The opening-tree discussion exposes a
mismatch between what the benchmark measures and what the coach needs.

## Standards

1. **P1 — Reindexing deletes existing data before a replacement is ready.**
   `experiments/rag/run.py:85-91` drops the collection before embedding. An Ollama
   failure then leaves the previous corpus deleted. The harness also permits a remote
   URI without checking that the target collection belongs to this experiment.
   **Fix:** build and validate an experiment-owned replacement before replacing data.
   *Standard source:* `security-and-hardening` skill, destructive-operation safeguards.

2. **P2 — Custom MinIO credentials break Milvus connectivity.**
   `docker-compose.yml:68-69` allows overriding MinIO credentials, but
   `docker-compose.yml:86-89` passes only the storage address to Milvus, which keeps
   using its default credentials.
   **Fix:** propagate matching credentials to both services.
   *Standard source:* `AGENTS.md` (environment-specific config), `docker-compose-patterns`.

3. **P2 — Embedding responses are insufficiently validated.**
   `backend/app/services/embeddings.py:96-104` checks vector count and dimensions but
   accepts strings, nulls, and nonfinite numbers inside vectors.
   **Fix:** validate finite numeric elements and raise `EmbeddingProviderError` on
   malformed output.
   *Standard source:* `security-and-hardening` (schema validation at boundaries).

4. **P2 — Experiment settings bypass the configuration rules.**
   `experiments/rag/run.py:62-73` constructs settings directly, so `OLLAMA_BASE_URL`
   from `.env` is ignored; CLI overrides use `model_copy` without revalidation
   (`--k -1` reaches retrieval).
   **Fix:** load environment-aware settings and validate the final experiment config.
   *Standard source:* `AGENTS.md` (validated settings object, env-specific values).

5. **P2 — Existing collections are accepted without compatibility checks.**
   `backend/app/services/milvus.py:60-70` loads an existing collection without verifying
   schema, dimension, or embedding identity. A same-dimensional model change can silently
   mix incompatible vectors.
   **Fix:** verify a collection manifest before use; require reindexing on incompatibility.
   *Standard source:* ADR 0006 (one embedding model/dimension per collection).

6. **P2 — Text storage limits are applied incorrectly.**
   `backend/app/services/milvus.py:197-202` truncates by characters while Milvus VARCHAR
   limits are in bytes; multibyte text can still exceed the declared limit.
   **Fix:** validate UTF-8 byte size before embedding and persistence.
   *Standard source:* `security-and-hardening` (length validation at boundaries).

## Spec

1. **P1 — Relevance judgments measure opening identity, not pedagogical usefulness.**
   `experiments/rag/scoring.py:21-28` accepts an ECO or opening-name match regardless of
   passage content. `experiments/rag/golden_set.json:5` even lets **Queen's Gambit Accepted**
   satisfy the query for **refusé** through the broad `"queen's gambit"` label.
   **Impact:** a TSV row can "answer" a coaching question without containing any
   explanation; the benchmark does not demonstrate RAG's added value over metadata lookup.

2. **P2 — The out-of-theory query is counted as an unavoidable failure.**
   `experiments/rag/golden_set.json:10` gives it no relevance labels, but
   `experiments/rag/run.py:96-107` scores it and `scoring.py:74-86` includes its zeros in
   the averages. The harness does not separately verify that it returns useful context.
   *Correction to the earlier verbal explanation:* the query is **not** excluded.

3. **P2 — Four TSV headers are ingested as opening records.**
   `experiments/rag/run.py:134-139` concatenates five TSVs, while
   `backend/app/ingestion/adapters.py:34-44` skips only the first header.
   **Impact:** the reported **3819 TSV records include four bogus records** (real total
   **3815**); their identical IDs collapse during upsert, so reported generated-chunk counts
   differ from stored collection cardinality.

4. **P1 — Results lack sufficient provenance for reproducibility.**
   `experiments/rag/run.py:221-239` records the original config rather than all effective
   overrides, a mutable model tag rather than its revision, and no retrieved hits. The
   `--no-ingest` path reuses a collection without checking it matches the current corpus,
   model, or configuration.
   **Impact:** a report can attribute results to inputs different from those actually
   indexed. The earlier claim that prose passages caused the score improvement was **not**
   established by saved retrieval evidence.

5. **P2 — The latency comparison is uncontrolled.**
   `experiments/rag/run.py:182-186` measures one sequential pass without a controlled
   warm-up. The published section result came from rescoring while the page result followed
   ingestion; the artifacts do not record the ingestion mode. The **66 ms vs 536 ms**
   comparison therefore does not establish a section-granularity latency advantage.

6. **P2 — Chunking does not implement the stated token/full-page contract.**
   `backend/app/ingestion/chunker.py:47-61,77-81` counts whitespace-separated words rather
   than model tokens and clips full pages too; `backend/app/services/milvus.py:202` can then
   truncate stored text after embedding. Section-to-full-page reconstruction is not
   evaluated.

## Boundaries

- The **opening-tree explorer is not a missing requirement** — it was discussed but not
  approved for implementation.
- The original plan explicitly requested TSV vectors, so their presence is not itself a
  spec violation.
- API wiring of `RagService`/`CoachService` and the ingestion CLI were explicitly deferred
  and are **not** certified as present.

## Summary

- **Standards:** 6 findings; worst = destructive reindexing before replacement succeeds.
- **Spec:** 6 findings; worst = identity-based relevance judgments do not validate
  pedagogical retrieval.
