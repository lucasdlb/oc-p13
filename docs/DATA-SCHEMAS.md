# External Data Schemas: Lichess Opening Explorer and Stockfish UCI

This document is the field-level reference for the external data sources used or considered by the POC (Lichess Opening Explorer, Lichess cloud evaluation, Stockfish UCI). It inventories everything each source can return, records what the backend currently retrieves, and lists the fields we discard or do not yet use as inspiration for visualization and coaching improvements.

It complements `docs/DATA.md` (sources, persistence, cache policy) and `docs/adr/0003-data-sources-and-source-validation-policy.md`. It does not replace them.

## Metadata and maintenance

| Item | Value |
| --- | --- |
| Scope | Lichess Opening Explorer HTTP API; Lichess cloud evaluation (`/api/cloud-eval`); Stockfish UCI engine protocol |
| Lichess spec version | `2.0.175` (`lichess-org/api`) |
| Snapshot date | 2026-10-01 |
| Primary sources | See [Sources](#sources) |
| Maintenance rule | Re-verify this document when the Lichess OpenAPI `info.version` changes, when `lila-openingexplorer` changes a response struct, or when the Stockfish UCI output format changes. |

Retrieval-map legend:

- **Retrieved?** `yes` = parsed by the backend; `no` = present in the API response but dropped.
- **Where** = code location in this repository.
- **Transformation** = how the raw value becomes our model value.

## Scope

In scope:

- Lichess Opening Explorer endpoints `/lichess`, `/masters`, `/player`, `/masters/pgn/{gameId}`.
- Lichess cloud evaluation (`/api/cloud-eval`), documented as a candidate deep-evaluation fast path (not yet implemented).
- Stockfish UCI handshake, options, `info` output, `bestmove`, and the `go`/`setoption` input surface.

The "famous games" material exposed by Opening Explorer itself (top games, recent games, master game PGN) stays in scope because it can feed the RAG/LLM context and richer visualizations.

### Out-of-scope sources

Documented here only to avoid re-discovery and to record the exclusion rationale.

| Source | Data kind | Why excluded |
| --- | --- | --- |
| Studies (`/api/study/*`) | User-authored opening courses and annotated games: `StudyMetadata {id, name, createdAt, updatedAt}`, study/chapter PGN move trees, chapter tags | User-generated, not a canonical opening database. A pedagogical RAG corpus is a plausible **improvement idea for an MVP, not for this POC** (requires a UGC and licensing validation pass). |
| FIDE (`/api/fide/player/*`) | Federation player identity and ratings: `FIDEPlayer {id, name, title, federation, year, standard, rapid, blitz, gender, photo}`, `FIDEPlayerRatings` | Player identity and rating, not opening knowledge. Would only calibrate the pedagogical level from a real rating; account/profile is out of POC scope. |
| Tournaments (`/api/tournament*`, `/api/swiss*`) | Event metadata and standings: `ArenaTournament {id, createdBy, clock, rated, fullName, nbPlayers, variant, startsAt, finishesAt, status, perf, min/maxRating, winner}`, `SwissTournament {round, nbRounds, nbPlayers, status, stats{games, whiteWins, blackWins, draws, byes, absences, averageRating}, verdicts}` | Competitive-event data with no opening-pedagogy use. |
| Tablebase (`/api/tablebase/{standard,atomic,antichess}`) | Perfect endgame results for <=7 pieces: `TablebaseJson {category, dtz, precise_dtz, dtc, dtm, dtw, checkmate, stalemate, variant_win/loss, insufficient_material, moves[]}`, `TablebaseMove` | Endgame oracle; only applies once a line reaches <=7 pieces, far outside the opening-phase demo. |
| Account, puzzles, TV | Profile, tactics, live games | Not POC features. |

## Data flow

```text
client FEN + UCI move line + level
  -> backend local opening match (opening_book.py, offline seed)
  -> Lichess Opening Explorer /lichess   (stats + opening + popular moves)
  -> Lichess Opening Explorer /masters   (masters stats + top games)
  -> MongoDB caches (lichess_cache, stockfish_cache)
  -> Stockfish UCI (out-of-theory evaluation)
  -> AnalyzePositionResponse (models/analysis.py)
```

The schema of each source enters the system exactly where the arrows show. Everything downstream of the external response is documented per section below.

## Lichess Opening Explorer

### Connection

- Host: `explorer.lichess.org` (not `lichess.org`).
- Auth: OAuth2 bearer token (`Authorization: Bearer <token>`). The spec declares `security: OAuth2: []` with no scope for `/lichess` and `/masters`. The POC uses a personal access token from `LICHESS_TOKEN`.
- Rate limiting: one request at a time; `429` means a limit was exceeded.
- CORS: `Access-Control-Allow-Origin: *`.
- Runs the open-source service `lichess-org/lila-openingexplorer`.
- POC behaviour: enabled by `config.toml [lichess]`, token from environment only. Disabled, missing token, unauthorized, unavailable, invalid, or empty stats all return the local seed and add a fallback to `fallbacks_used` (`backend/app/services/lichess.py`).

### Query parameters

| Endpoint | Parameter | Type | Default | Max | Description | Used by POC |
| --- | --- | --- | --- | --- | --- | --- |
| `/lichess`, `/masters`, `/player` | `variant` | string | `standard` (POC) / `chess` (player) | - | Chess variant to look up. | `/lichess`: `standard`; `/masters`: not sent |
| `/lichess`, `/masters`, `/player` | `fen` | string | starting position | - | Root position as X-FEN/EPD; statistics come from games reaching it. | no (POC sends `play`) |
| `/lichess`, `/masters`, `/player` | `play` | comma-separated UCI | `""` | - | Legal moves played from `fen`; the resulting position is looked up. Required to name an opening when `fen` is not an exact named position. | yes |
| `/lichess` | `speeds` | array (`Speed`) | all | - | Game speeds to include. Omitted = all speeds. | no |
| `/lichess` | `ratings` | array of int enum | all | - | Rating groups to include; each group spans from its value to the next bucket. Omitted = all ratings. | yes (from level preset or request override) |
| `/lichess` | `since` | `YYYY-MM` | `1952-01` | - | Include only games from this month or later. | no |
| `/lichess` | `until` | `YYYY-MM` | `3000-12` | - | Include only games from this month or earlier. | no |
| `/lichess`, `/masters`, `/player` | `moves` | integer | `12` (`/player`: all) | - | Number of most common next moves to display. Caps the `moves[]` array only; it does not change the top-level outcome totals. | yes (`recommendations.default_moves`) |
| `/lichess` | `topGames` | integer | `4` | `4` | Maximum number of top games to include (highest level). | no |
| `/lichess` | `recentGames` | integer | `4` | `4` (or `8`) | Maximum number of most recent games to include. | no |
| `/lichess` | `history` | boolean | `false` | - | Include per-month win/draw/loss history for the position. | no |
| `/masters` | `since` | year | `1952` | - | Include only games from this year or later. | no |
| `/masters` | `until` | year | - | - | Include only games from this year or earlier. | no |
| `/masters` | `topGames` | integer | `15` | `15` | Maximum number of top master games to include. | no |
| `/player` | `player` | username | required | - | Username whose games are used to build the statistics. | no (endpoint unused) |
| `/player` | `color` | `white`/`black` | required | - | Only count games where `player` had this color. | no |
| `/player` | `modes` | array (`rated`/`casual`) | all | - | Game modes to include. | no |
| `/player` | `recentGames` | integer | all | - | Maximum number of recent games to include. | no |

`moves=12` means "return the 12 most-played next moves". The list is ranked by frequency (games count) among the games that match the filters, so raising it shows rarer candidates and lowering it shows only the most popular. The top-level `white`/`draws`/`black` count **all** games reaching the position, not just the displayed moves, so they are not the sum of `moves[]`.

Ratings buckets accepted by `/lichess`: `0`, `1000`, `1200`, `1400`, `1600`, `1800`, `2000`, `2200`, `2500`. The POC maps its level presets onto these buckets (`RATING_BUCKETS` in `analysis.py`).

Source: `doc/specs/tags/openingexplorer/{lichess,masters,player}.yaml` (Lichess OpenAPI), `lila-openingexplorer/README.md`.

### Shared sub-objects

`Opening` (`OpeningExplorerOpening.yaml`):

| Field | Type | Notes |
| --- | --- | --- |
| `eco` | string | ECO code, e.g. `D10` |
| `name` | string | Opening name |

`GamePlayer` (`OpeningExplorerGamePlayer.yaml`):

| Field | Type | Notes |
| --- | --- | --- |
| `name` | string | Player name; may be `null` for anonymous games (as seen in the `lila-openingexplorer` README example) |
| `rating` | integer | Player rating; may be `null` |

`Speed` (`Speed.yaml`): `ultraBullet`, `bullet`, `blitz`, `rapid`, `classical`, `correspondence`.

`LichessGame` (`OpeningExplorerLichessGame.yaml`):

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Lichess game id |
| `winner` | `white` / `black` / `null` | Winning color; `null` = draw |
| `speed` | `Speed` | Game speed |
| `white` | `GamePlayer` | White player (name and rating) |
| `black` | `GamePlayer` | Black player (name and rating) |
| `year` | number | Year the game was played |
| `month` | string / `null` | Month played (`YYYY-MM`); may be `null` |
| `mode` | `rated` / `casual` | Whether the game was rated; present in official examples and in the service README, not listed in the schema file |

`MastersGame` (`OpeningExplorerMastersGame.yaml`):

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Master game id, usable with `/masters/pgn/{gameId}` |
| `winner` | `white` / `black` / `null` | Winning color; `null` = draw |
| `white` | `GamePlayer` | White player (name and rating) |
| `black` | `GamePlayer` | Black player (name and rating) |
| `year` | integer | Year the game was played |
| `month` | string | Month played (`YYYY-MM`) |

Masters games have no `speed` or `mode`.

### `GET /lichess` response

Schema: `OpeningExplorerLichess.yaml`. Required top-level: `opening`, `white`, `draws`, `black`, `moves`, `topGames`.

| Field | Type | Meaning | Retrieved? | Where | Transformation |
| --- | --- | --- | --- | --- | --- |
| `white` | integer | Number of games reaching the position that White won (all moves). | yes | `lichess.py:30-35`, `:100` | share = `round(white/total, 4)` |
| `draws` | integer | Number of games reaching the position that were drawn. | yes | `lichess.py:100` | share = `round(draws/total, 4)` |
| `black` | integer | Number of games reaching the position that Black won. | yes | `lichess.py:100` | share = `round(black/total, 4)` |
| `opening.eco` | string | ECO code of the named position, or `null` if unnamed. | yes | `lichess.py:16-18`, `:175-183` | `Opening.eco` |
| `opening.name` | string | Opening name, or `null` if unnamed. | yes | `lichess.py:16-18`, `:175-183` | `Opening.name` |
| `moves[].uci` | string | Next move in UCI notation. | yes | `lichess.py:21-27`, `:186-208` | `RecommendedMove.uci` |
| `moves[].san` | string | Next move in SAN notation. | yes | same | `RecommendedMove.san` |
| `moves[].averageRating` | integer | Average rating of the players who played this move. | yes | same | `RecommendedMove.average_rating` |
| `moves[].white` | integer | White wins among games that played this move. | yes | same | share = `round(white/games, 4)` |
| `moves[].draws` | integer | Draws among games that played this move. | yes | same | share = `round(draws/games, 4)` |
| `moves[].black` | integer | Black wins among games that played this move. | yes | same | share = `round(black/games, 4)` |
| `moves[].game` | `LichessGame` / `null` | One representative game for this move, or `null`. | no | - | dropped |
| `moves[].opening` | `Opening` / `null` | Named opening reached by this move, or `null`. | no | - | dropped (per-move opening name) |
| `topGames[]` | array of `LichessGame` + `uci` | Highest-level games reaching the position, with the move played. | no | - | dropped |
| `recentGames[]` | array of `LichessGame` + `uci` | Most recent games reaching the position. | no | - | dropped |
| `history[]` | array of `{month, white, draws, black}` | Per-month outcome totals for the position. | no | - | dropped (only returned when `history=true`) |

`total = white + draws + black`. If `total <= 0` the client returns the seed fallback `lichess_empty_stats`.

Official example (spec `examples/openingExplorer-lichess.json.yaml`) includes, for each move, a `game` (usually `null`) and an `opening` that is non-null only for moves that reach a named position, plus up to 4 `recentGames` and 4 `topGames` with players, ratings, speed, mode, year, month.

### `GET /masters` response

Schema: `OpeningExplorerMasters.yaml`. Required top-level: `opening`, `white`, `draws`, `black`, `moves`, `topGames`.

| Field | Type | Meaning | Retrieved? | Where | Transformation |
| --- | --- | --- | --- | --- | --- |
| `white` | integer | Master games reaching the position that White won (all moves). | yes | `lichess.py:142-153` | share, source `masters-opening-explorer` |
| `draws` | integer | Drawn master games reaching the position. | yes | same | share |
| `black` | integer | Master games reaching the position that Black won. | yes | same | share |
| `opening.eco` | string | ECO code of the named position, or `null`. | yes | `lichess.py:154`, `:175-183` | `Opening`, source `lichess-opening-explorer` |
| `opening.name` | string | Opening name, or `null`. | yes | same | `Opening` |
| `moves[].uci` | string | Next move in UCI notation. | yes | `lichess.py:155`, `:186-208` | `RecommendedMove`, source `masters-opening-explorer` |
| `moves[].san` | string | Next move in SAN notation. | yes | same | `RecommendedMove` |
| `moves[].averageRating` | integer | Average rating of the master players who played this move. | yes | same | `average_rating` |
| `moves[].white` / `draws` / `black` | integer | Outcomes among master games that played this move. | yes | same | shares |
| `moves[].game` | `MastersGame` / `null` | One representative master game for this move, or `null`. | no | - | dropped |
| `moves[].opening` | `Opening` / `null` | Named opening reached by this move, or `null`. | no | - | dropped |
| `topGames[]` | array of `MastersGame` + `uci` | Top master games reaching the position. | no | - | dropped (up to 15, famous OTB games) |

`masters_moves` is kept separate from Lichess recommendations on purpose (`docs/DATA.md`): it shows theory rather than popular play.

### `GET /player` response (NDJSON, unused)

Streams `application/x-ndjson` with progressive rows while the player is indexed. Fields:

| Field | Type | Notes |
| --- | --- | --- |
| `white` / `draws` / `black` | integer | totals from this position |
| `moves[]` | array | `uci`, `san`, `white`, `draws`, `black`, `averageOpponentRating` (integer or `null`), `game` (single game for that move) |
| `recentGames[]` | array | up to ~15, with `uci`, game object |
| `opening` | `Opening` | |
| `queuePosition` | integer | indexing queue status |

Useful later for "how does this specific young player perform in this position" coaching; not used today.

### `GET /masters/pgn/{gameId}` (unused)

Returns `application/x-chess-pgn` (text PGN) for a master game id from `topGames`. Useful to embed a real annotated reference game into the coach context.

## Lichess cloud evaluation (`/api/cloud-eval`)

In scope as a candidate deep-evaluation fast path. Not implemented today: the current backend always runs the local Stockfish binary.

- Endpoint: `GET https://lichess.org/api/cloud-eval` (host `lichess.org`, not `explorer.lichess.org`).
- Auth: none (`security: []`).
- Rate limited. The spec advises using it for a few positions at a time; for bulk lookups use the exported evaluations database.
- Coverage: about 320 million pre-computed positions, weighted towards opening positions. Returns `404` when the position is absent.

Query parameters:

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `fen` | string | required | X-FEN of the position |
| `multiPv` | integer | `1` | Number of variations; up to 5 may be available. The API can return more than requested. |
| `variant` | string | `standard` | Variant key |

Response (`CloudEval.yaml`):

| Field | Type | Notes |
| --- | --- | --- |
| `fen` | string | Reduced FEN: pieces, active color, castling, en passant only |
| `knodes` | integer | Kilo-nodes searched to produce the stored evaluation |
| `depth` | integer | Depth reached by the engine that produced it |
| `pvs[]` | array | Each `{cp or mate, moves}`; `cp`/`mate` are from **White's** point of view; `moves` is in UCI (Chess960 castling) |

On `404`, the body is `{"error": "..."}`.

Official example (`r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3`): `depth 60`, `knodes 203656`, two `pvs` at `cp 18` and `cp 19`.

### Compared with local Stockfish

| Aspect | Lichess cloud eval | Local Stockfish (`stockfish.py`) |
| --- | --- | --- |
| Nature | Lookup in a pre-computed database | Live computation |
| Latency | Instant on hit, plus network round trip | CPU-bound (`timeout_seconds`, default 5 s) |
| Depth | Stored, varies (often 20-60), not selectable | Fixed to `settings.depth` (12) |
| Score perspective | White | Side to move |
| Variations | Up to 5 PVs | 1 PV (`MultiPV=1`) |
| Coverage | Biased to openings, `404` elsewhere | Any legal position |
| Dependency | Remote `lichess.org` + rate limit | Local binary, no network |
| Source label | `lichess-cloud-eval` | `stockfish` |
| Data license | CC0 (exported evaluations database) | GPL engine |

### Proposed integration (not implemented)

```text
FEN
  -> cloud-eval lookup
       200 -> use it (source: lichess-cloud-eval, White POV, deep, N PVs)
       404 / error -> local Stockfish (source: stockfish, side-to-move POV)
  -> normalize both to one score convention + a perspective field
  -> cache only 200s under a distinct key/source; never cache 404
```

This keeps local Stockfish as the guaranteed non-negotiable path (`docs/AGENT_CONTEXT.md`) and uses cloud eval as an optional fast path with local fallback. It introduces a second score perspective, so `score` should gain an explicit `perspective` field to avoid sign confusion in the UI.

## Stockfish (UCI protocol)

Reference: official Stockfish wiki, [UCI Protocol and Stockfish Commands](https://official-stockfish.github.io/docs/stockfish-wiki/UCI-Protocol-and-Stockfish-Commands.html). Implementation: `backend/app/services/stockfish.py`.

### Handshake

On `uci`, the engine emits `id name <engine>`, `id author <...>`, a list of `option name ... type ... default ... [min ... max ...]` lines, then `uciok`.

- POC uses only `id name` to derive the cache key engine version (`engine_version()` in `stockfish.py:12-43`, cached per binary).
- All options are ignored. Available options (Stockfish 19 defaults): `Threads` (spin 1-1024), `Hash` (spin 1-33554432), `MultiPV` (spin 1-256/500), `Clear Hash` (button), `Ponder` (check), `Move Overhead`, `nodestime`, `UCI_Chess960`, `UCI_LimitStrength`, `UCI_Elo` (1320-3190), `UCI_ShowWDL`, `SyzygyPath`, `SyzygyProbeDepth`, `Syzygy50MoveRule`, `SyzygyProbeLimit`, `EvalFile`, `Debug Log File`, `NumaPolicy`, `Skill Level` (0-20).

### `info` output fields

| Field | Meaning | Retrieved? |
| --- | --- | --- |
| `depth` | nominal search depth | no (we echo the requested `settings.depth`) |
| `seldepth` | deepest selective depth | no |
| `multipv` | line index when `MultiPV > 1` | no (we run `MultiPV=1`) |
| `score cp <x>` | centipawn score | yes (`type=cp`) |
| `score mate <x>` | mate distance in moves | yes (`type=mate`) |
| `score ... upperbound` / `lowerbound` | bound flag | no |
| `wdl <w> <d> <l>` | win/draw/loss permille (needs `UCI_ShowWDL`) | no |
| `nodes` | nodes searched | no |
| `nps` | nodes per second | no |
| `hashfull` | transposition table usage (per mille) | no |
| `tbhits` | tablebase hits | no |
| `time` | elapsed ms | no |
| `pv <moves...>` | principal variation in UCI | no |
| `currmove` / `currmovenumber` | progress info | no |
| `refutation` / `currline` | refutation lines | no |
| `info string ...` | free text / errors | no |

`bestmove <move> [ponder <move>]`: POC takes the first token only; `ponder` is ignored.

`score` perspective: the UCI score is from the side to move's point of view. The POC stores it as-is and does not normalize to White's point of view; the frontend renders `{type, value}` without a perspective qualifier.

### `go` and `setoption` input surface

| Command | Used by POC |
| --- | --- |
| `go depth <n>` | yes (`settings.depth`, default 12) |
| `go movetime` / `nodes` / `mate` / `infinite` | no |
| `go wtime` / `btime` / `winc` / `binc` / `movestogo` | no |
| `go searchmoves ...` | no |
| `go ponder` / `ponderhit` | no |
| `setoption name ...` | no (no `Threads`, `Hash`, `MultiPV`, `UCI_ShowWDL`, strength limits) |
| `position fen <fen>` | yes |
| `position ... moves ...` | no |
| `ucinewgame` / `isready` | yes (`isready`; `ucinewgame` not sent) |

### Current Stockfish response model

`stockfish.py:127-149` produces:

```json
{
  "status": "ok",
  "best_move": "g1f3",
  "score": {"type": "cp", "value": 24},
  "depth": 12
}
```

Failure shape: `{"status": "unavailable", "reason": "binary_not_found" | "process_error" | "timeout" | "invalid_uci_output"}`. Only `status: ok` results are cached.

## Persistence schemas as stored

Collection and key policy is defined by `docs/adr/0005-mongodb-sessions-and-cache-policy.md` and `backend/app/services/cache_store.py`.

`lichess_cache` document (shared by `/lichess` and `/masters`, distinguished by key prefix):

```json
{
  "key": "explorer|standard|e2e4,e7e5|1000,1200",
  "payload": {
    "stats": {"source": "lichess-opening-explorer", "games": 100, "white": 0.5, "draws": 0.1, "black": 0.4},
    "opening": {"eco": "C20", "name": "King's Pawn Game", "matched": true, "source": "lichess-opening-explorer"},
    "recommended_moves": []
  },
  "cached_at": "2026-10-01T00:00:00Z"
}
```

The payload stores the **mapped** model, so raw counts, `topGames`, `recentGames`, `history`, and per-move games are not persisted. Key shapes: `explorer|standard|<moves>|<ratings>` and `masters|<moves>`. TTL `mongodb.lichess_cache_ttl_seconds` (24 h).

`stockfish_cache` document:

```json
{
  "key": "stockfish|<epd>|d12|Stockfish 16.1",
  "payload": {"status": "ok", "best_move": "g1f3", "score": {"type": "cp", "value": 24}, "depth": 12},
  "cached_at": "2026-10-01T00:00:00Z"
}
```

Key shape `stockfish|<epd>|d<depth>|<engine_version>`. No TTL: a new engine binary changes the version component and invalidates old entries.

`videos_cache`: reserved for the YouTube phase, key `videos|<normalized query>`, TTL 7 d (unused today).

`sessions` document (`session_store.py`): `started_at`, `ended_at`, `status`, embedded `moves[]{ply, uci, san, fen, pgn, created_at}`, embedded `analyses[]{position_key, fen, response, created_at}` where `response` is the full `AnalyzePositionResponse` dump.

## Retrieval audit summary

| Source capability | Provided by API | Retrieved by POC | Impact |
| --- | --- | --- | --- |
| Win/draw/loss totals | yes | yes (as percentages) | Raw integer counts and exact sample sizes are lost at model boundary; `games` is reconstructed |
| Opening eco/name (position) | yes | yes | Full |
| Popular moves + stats | yes | yes | Full |
| Per-move opening names | yes | no | Could deepen advice and visualization |
| Reference games (top/recent) | yes | no | Could feed RAG/LLM with real famous games |
| History over time | yes | no | Could add a trend visualization |
| Player-specific stats | yes | no | Out of current product scope |
| Master game PGN | yes | no | Could enrich coach context |
| Query filters (speeds/dates/games) | yes | mostly no | Current queries always use defaults; cache key omits unused params |
| Stockfish PV / MultiPV | yes | no | Could show continuations and alternatives |
| Stockfish WDL | yes | no | Could show probabilistic outcomes |
| Stockfish search accounting (nodes/nps/time/seldepth/tbhits) | yes | no | Could drive a confidence indicator |
| Stockfish score perspective | side-to-move | not normalized | UI shows a number without White/Black perspective |
| Lichess cloud eval (deep PVs, White POV) | yes | no | Candidate fast path / deep evaluation; see the cloud eval section |

Correctness notes discovered during the audit:

- Lichess payload models are strict: `white`, `draws`, `black` are required on both the top-level payload and each move. A response missing any of them raises `ValidationError` and degrades to the seed fallback rather than treating the value as zero.
- The cache stores mapped percentages, not raw counts, so any future feature that needs exact game counts must change the cache payload or cache the raw response.
- The `depth` echoed by the backend is the requested depth, not the depth actually reported by the engine in the final `info` line.
- Lichess cloud eval is documented but not implemented. Adding it means two score conventions coexist (cloud eval is White POV, local Stockfish is side-to-move POV); normalize before display.

## Opportunity catalog

Grouped by theme. "Planned?" references `TODO.md` and `IMPROVEMENT.md` where the idea already exists.

### Famous games as LLM/RAG context

The single richest unused surface: `topGames`, `recentGames`, `moves[].game`, and `/masters/pgn/{gameId}`.

| Idea | Source fields | Value | Planned? |
| --- | --- | --- | --- |
| "Played by X vs Y (event, year)" annotation on a recommended move | `moves[].game.{white,black,year,month,id}` | Concrete, sourced example for a move | no |
| Inject 1-2 annotated master games into `rag_context` | `topGames[]` + `/masters/pgn/{gameId}` | Grounds the coach in real games, satisfies source-traceability rule | no |
| "Theory vs practice" comparison | `masters_moves` vs Lichess `moves` | Explain where masters deviate from the crowd | partially (both fetched, not compared) |
| Recent trend / recency check | `recentGames[].year`/`month` | Warn when a "popular" move is dated or current | no |

### Visualization improvements

| Idea | Source fields | Value | Planned? |
| --- | --- | --- | --- |
| Per-move opening name | `moves[].opening` | Label each candidate by the opening it leads to | no |
| Frequency-over-time sparkline | `history[]` (`history=true`) | Show whether a move is gaining or fading | no |
| Richer game cards (players, ratings, speed, mode) | `topGames`/`recentGames` fields | Replace the plain move table with recognizable examples | no |
| Average opponent rating context | `moves[].averageRating` | Already shown as a badge; could be labeled explicitly | partial (`average_rating`) |
| Exact sample sizes | raw `games` counts | Precise "based on N games" instead of reconstructed totals | no |
| Stockfish continuation line | `info pv` | Show the expected next moves | yes (`IMPROVEMENT.md` ideas 2, 7) |
| MultiPV alternatives | `info multipv` | Show top 3 moves | yes (`IMPROVEMENT.md` idea 1) |
| WDL bars | `info wdl` | Win/draw/loss estimate | yes (`IMPROVEMENT.md` idea 6) |

### Chess advice improvements

| Idea | Source fields | Value | Planned? |
| --- | --- | --- | --- |
| Blunder detection before/after a move | `score` on two positions | Explain why a move loses ground | yes (`IMPROVEMENT.md` idea 3) |
| "Loses ~X pawns" phrasing | `score cp` | Concrete, sourced explanation | yes (`IMPROVEMENT.md` idea 4) |
| Mate / tactic detection | `score mate`, `pv` | Highlight forced sequences | yes (`IMPROVEMENT.md` idea 5) |
| Compare player's move to engine best | `bestmove`, `pv` | Coaching feedback | yes (`IMPROVEMENT.md` idea 9) |
| Confidence indicator | `depth`, `seldepth`, `nodes`, `time`, `hashfull` | Tell the user how reliable the evaluation is | yes (`IMPROVEMENT.md` idea 7) |
| Normalize score perspective | `score` side-to-move | Avoid sign confusion in the UI | no |
| Player-specific opening advice | `/player` endpoint | "You personally score poorly here" | no (out of POC scope) |
| Fast path / deep evaluation | cloud-eval `depth`, `pvs` (White POV) | Skip the local engine on common opening positions and get deeper evaluations with up to 5 PVs | no (new candidate) |

## Sources

- Lichess API reference: <https://lichess.org/api> (host for Opening Explorer: `explorer.lichess.org`).
- Lichess OpenAPI repository: <https://github.com/lichess-org/api> (`doc/specs/`, version `2.0.175`); cloud eval spec: `doc/specs/tags/analysis/api-cloud-eval.yaml`, `doc/specs/schemas/CloudEval.yaml`.
- Opening Explorer service: <https://github.com/lichess-org/lila-openingexplorer>.
- Lichess cloud evaluation endpoints: <https://lichess.org/api#tag/Analysis/operation/apiCloudEval>.
- Lichess evaluated positions database (CC0): <https://database.lichess.org/#evals>.
- Lichess opening names dataset: <https://github.com/lichess-org/chess-openings> (CC0, to confirm at ingestion).
- Stockfish UCI protocol and commands: <https://official-stockfish.github.io/docs/stockfish-wiki/UCI-Protocol-and-Stockfish-Commands.html>.
- Stockfish repository: <https://github.com/official-stockfish/Stockfish>.

## Related documents

- `docs/DATA.md`: sources, roles, MongoDB/Milvus persistence, cache policy.
- `docs/adr/0003-data-sources-and-source-validation-policy.md`: source validation policy.
- `docs/adr/0005-mongodb-sessions-and-cache-policy.md`: cache keys, TTLs, degradation.
- `IMPROVEMENT.md`: Stockfish improvement ideas and agentic architecture options.
