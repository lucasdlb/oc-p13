# Chess-openings in RAG — pertinence and better uses

> Non-authoritative discussion / design note. It records an analysis, **not a decision**.
> A decision to change the role of `chess-openings` is structural and would require an
> ADR update (ADR 0006 currently assigns it "short disambiguation docs" in Milvus).
> Sources of truth remain `docs/` and `docs/adr/`.

- **Date:** 2026-10-01
- **Origin:** challenge raised during the Phase R review: "the golden queries are mostly
  opening names, so why use RAG instead of a metadata lookup? Is `chess-openings` even
  pertinent as RAG material?"

## Question

Should `lichess-org/chess-openings` be ingested into Milvus as RAG content, or used
differently — for example as a structured opening tree for anticipation and comparison?

## What the dataset actually is

`lichess-org/chess-openings` is **structured metadata**, not prose. Columns are `eco`,
`name`, `pgn` (3819 rows over `a`–`e`). Each row is a named node identified by a move
sequence. Evidence from the corpus:

- Node: `C60 Ruy Lopez = 1. e4 e5 2. Nf3 Nc6 3. Bb5`.
- Its children are named continuations:
  `3...Bb4` (Alapin Defense), `3...g6` (Fianchetto Defense), `3...Nge7` (Cozio Defense),
  `3...a5` (Bulgarian Variation), `3...Be7` (Lucena Variation), …
- Names encode the tree: `Ruy Lopez` → `Ruy Lopez: Alapin Defense` →
  `Ruy Lopez: Alapin Defense, Alapin Gambit` (prefix `:` per level, `,` per sub-level).
- Branches are deep (rows up to ~54 plies) → real "theory depth" per branch.
- **Transpositions exist**: the same position is reachable by different move orders
  (e.g. "Pseudo-Slav"/"Pseudo-Chigorin" appear under different orders in `D02` vs `D06`).
- The rows are **named nodes with gaps**: a deep line may have no named row for its
  intermediate positions.

Conclusion: it is a **labeled game tree / opening forest**, best modelled as a trie plus a
position index — not as a document corpus.

## Does it pass the "good RAG material" test?

A retrieval corpus wants chunks that are (a) **distinct** and (b) **contain the answer
text**. `chess-openings` fails both:

- **Not distinct**: thousands of near-duplicate lines ("Sicilian Defence, …" × N) whose
  embeddings cluster tightly.
- **No answer text**: it answers "which opening is this?" (identification), not
  "why / what is the plan / what is the trap?" (explanation).

It also dominates the store: 3819 of ~3832 chunks are these one-liners around only ~63
prose chunks (13 Wikibooks pages). That is why the Phase R benchmark degenerated into name
lookups and scored 7/15 at nDCG 1.0 purely on metadata rows.

There is also an existing documentation tension: `docs/DATA.md:137` says Milvus must not
contain "la source canonique du matching" (which `chess-openings` is), while ADR 0006
promised short disambiguation docs in Milvus.

## Where it is pertinent

It is important to the system, just not as vector content:

1. **MongoDB `openings`** — the canonical matching source (`docs/DATA.md`), replacing the
   3-entry `opening_book.py` seed (the pending migration).
2. **`eco_code` as join/filter key** — constrains RAG retrieval to the identified opening.
3. **Alias/dictionary role** — mapping `name ↔ eco ↔ line`, and FR→EN aliases (the
   "ouverture espagnole" → `C60`/Ruy Lopez gap), preferably as query-time expansion rather
   than indexing thousands of metadata vectors.

## Better uses: an opening tree (proposal, not approved)

### Data model

Two keys over the same named nodes:

- **Path key** (move order): `path_key = "e2e4 e7e5 g1f3 b8c6 f1b5"`, plus
  `parent_path_key` and ancestor `prefix_keys`.
- **Position key**: `epd` (placement + side + castling + ep), which merges transpositions.

Per node: `san`, `pgn`, `uci`, `fen`, `epd`, `eco`, `name`, `depth`, `last_move`,
`subtree_size` (named descendants = branch richness), `parent_path_key`. Built offline,
deterministically, with `python-chess` (SAN → UCI → EPD).

### Runtime module (`OpeningTree`), deep interface

- `identify(moves)` — exact path → deepest known ancestor prefix → EPD transposition;
  confidence + alternates.
- `path(moves)` — named timeline traversed.
- `explore(moves)` — the anticipation primitive: enumerate **legal next moves**, annotating
  each with the named opening it leads to (deepest named descendant) and theory depth;
  unnamed moves returned as "out of theory".
- `compare(moves)` — the continuation list scored across axes.
- `coverage(moves)` — theory presence/depth; drives sortie detection and the Stockfish trigger.
- `by_alias(text)` — FR/EN name resolution.

### What it unlocks

1. **Anticipation panel**: legal next moves, each labeled with the opening it leads to and
   theory depth behind it.
2. **Comparison across axes**: theory richness (`subtree_size`), Lichess popularity,
   Stockfish eval, ECO/name, depth — ranked by pedagogical level.
3. **Opening timeline**: chain of named ancestors.
4. **Better `recommended_moves`**: theory continuations ∪ popularity ∪ eval, each named/sourced.
5. **Principled sortie detection**: replace the heuristic in `_run_stockfish_if_needed`
   with `coverage`.
6. **Grounded coach facts**: "You are in the Ruy Lopez (C60); main named continuations are
   3...a6 (Morphy Defence, C68) and 3...Nf6 (Berlin Defence, C65)."
7. **FR aliases** without vectors: alias map keyed to a node.

### How it composes with RAG

- **Tree = "what / which / next / how theoretical"** (deterministic metadata).
- **RAG = "why / plan / idea / trap"** (prose), retrieved by joining on `eco_code` / node
  name.
- The tree supplies the `eco_code` filter and a good query (`node.name + question`); the
  coach cites the tree node id for structural claims and the RAG chunk id for prose claims.

## Evaluation implications

Add a metadata-only eval track alongside the prose RAG eval:

- identification accuracy (exact / prefix / EPD),
- next-move naming accuracy,
- transposition recall,
- sortie-detection precision/recall against MVP scenario 3.

These are deterministic and run without Milvus/Ollama, cleanly separating "did we
identify/anticipate" from "did RAG find the explanation".

## Risks / details to settle

- SAN → UCI/EPD parsing (annotations like `Qh4#`, castling `O-O`, promotions); skip+warn on
  unparseable rows.
- Precedence when one EPD has several names, or one path has duplicate names (e.g.
  "Gedult Gambit" appears twice).
- Defining "next named continuation" across unnamed gaps (subtree scan, not literal child edge).
- Dataset coverage is not a judgement of move quality: a named branch is not necessarily
  recommended, and an absent branch is not proof of leaving theory.
- Migration pulls the pending `openings` MongoDB migration forward.

## Open questions (not decided)

1. Where does the tree live in this POC — MongoDB now, or an offline JSON/in-memory module
   first and Mongo later?
2. Interaction surface — fold `next_moves` / `opening_path` into `POST /api/analyze-position`,
   or add a dedicated `GET /api/openings/{fen}`?
3. Do we keep any `chess-openings` rows in Milvus at all (e.g. a small curated disambiguation
   set), or remove them entirely and rely on the tree + prose?
