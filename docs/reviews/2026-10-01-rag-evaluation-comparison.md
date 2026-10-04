# RAG evaluation comparison

> Non-authoritative review artifact. The current RAG design decisions remain in
> `docs/adr/0006-rag-milvus-and-embeddings.md`. This note records a comparison
> with the public reference repository and identifies possible follow-up work.

- **Date:** 2026-10-01
- **Reference repository:** [richardhugou/p13-agent-ia-echecs](https://github.com/richardhugou/p13-agent-ia-echecs)
- **Reference evaluation script:** [`evaluation/evaluer.py`](https://github.com/richardhugou/p13-agent-ia-echecs/blob/main/evaluation/evaluer.py)
- **Reference gold set:** [`evaluation/gold_set.yml`](https://github.com/richardhugou/p13-agent-ia-echecs/blob/main/evaluation/gold_set.yml)

## Reference evaluation

The reference repository compares two retrieval configurations:

- `A_naif`: fixed windows, no instruction prefix, no opening filter, top-3;
- `B_soigne`: section-aware chunks, 15% overlap, breadcrumbs, instruction-prefixed queries, opening/ECO filtering, top-5.

Its gold set contains 15 direct questions, 5 FEN/position questions, and 5
unsupported or trap questions. It reports:

- `Recall@k`;
- `MRR`;
- a top-score abstention threshold;
- correctly rejected traps and legitimate queries wrongly rejected;
- retrieval p50/p95 latency;
- end-to-end latency;
- illegal chess moves in generated recommendations.

The committed result reports `Recall@k = 1.0` and `MRR = 1.0` for both runs,
`4/5` correctly rejected traps, and `7.1 ms` retrieval p95 for the careful
configuration. The repository README also claims `5/5` trap rejection, which
does not match the committed `evaluation/resultats.json`.

## Measurement limitation

The reference evaluator scores opening-family identity, not passage usefulness:

```python
trouvees = [h["entity"]["ouverture"] for h in hits]
rank = next((i + 1 for i, o in enumerate(trouvees)
             if o in cas["attendu"]), None)
```

Any passage in the expected opening family counts as relevant, including a
history or reference section that may not answer the question. Its `Recall@k`
therefore measures whether retrieval stayed in the correct opening rayon, not
whether the retrieved passage supports the pedagogical answer.

The abstention threshold is also chosen from the same gold-set scores used for
evaluation. That is useful for exploration but is not a held-out threshold
evaluation. The reference notebook shows overlap between legitimate and trap
scores, so similarity alone cannot provide a reliable global abstention rule.

## Design difference

The reference repository implements constrained opening retrieval:

```text
position/question -> opening rayon -> Milvus filter -> semantic retrieval -> answer
```

This repository intentionally separates structured opening truth from
pedagogical prose:

```text
position/question -> structured opening lookup -> prose retrieval -> sourced answer
```

The reference corpus is substantially larger: approximately 161 selected pages
and 477 fiches across eight opening families. This repository currently measures
13 curated Wikibooks pages and, since the 2026-10-02 structural cleaning pass, 52 prose section
chunks. The earlier 63-chunk run included theory tables and navigation sections and is superseded.
Both use Qwen3-Embedding-0.6b,
1024 dimensions, cosine similarity, and Milvus HNSW.

The reference uses an opening/ECO filter as a hard safety boundary. This
repository has the metadata needed for a soft ECO filter, but the Phase R
benchmark did not apply it and the harness embeds raw golden queries rather
than the production retrieval query built by `prompt_context.py`.

## Relative strengths

The reference repository does better at:

- exercising the production retrieval path with FEN-derived context;
- evaluating unsupported-query behavior as a product concern;
- measuring end-to-end latency and illegal chess outputs;
- comparing a naive and a constrained retrieval configuration;
- preventing cross-opening contamination through signed opening rayons.

This repository does better at:

- keeping structured opening data out of the prose vector corpus;
- judging relevance at page/section passage level;
- preserving detailed run provenance and retrieved evidence;
- exposing the quality difference between page retrieval and section retrieval;
- avoiding the claim that finding the right opening name proves pedagogical retrieval.

## Recommended combined procedure

1. Keep the separation between structured opening data and prose knowledge.
2. Add a signed opening-ray filter as a safety constraint when the position or
   question identifies a supported opening.
3. Run the benchmark through the production retrieval-query builder.
4. Retain passage-level graded judgments as the primary retrieval evaluation.
5. Add opening-family accuracy as a separate routing metric.
6. Treat unsupported queries as first-class cases and report false-context rate,
   correct abstention rate, and legitimate rejection rate.
7. Add end-to-end checks for legal moves, theory/motor routing, source validity,
   answer grounding, and latency.
8. Select the abstention threshold on a development set and evaluate it on a
   frozen test set.

The two repositories' headline retrieval scores are not directly comparable:
the reference score is primarily opening-ray classification, whereas this
repository's section score measures whether the explanatory passage was found.
