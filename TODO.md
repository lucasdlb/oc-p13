# Implementation Plan

> Temp working file, non-authoritative. `docs/PLAN.md` and `docs/DATA.md` remain the
> sources of truth. Decisions are captured in `docs/adr/0005-mongodb-sessions-and-cache-policy.md`.

## Verification (2026-10-01)

- Backend: `uv run pytest backend/tests` — 81 passed.
- Frontend: `npm test -- --watch=false` — 14 passed; `npm run build` OK (pre-existing CSS budget warning in `analysis-panel.css`).

## Confirmed Decisions

| # | Decision | Value |
|---|---|---|
| 1 | MongoDB role | Sessions + Lichess/Stockfish/videos caches; never opening source or vector store |
| 2 | Session creation | Lazy: created on the first analyzed move; then every new move is appended |
| 3 | Reinitialise | No session if nothing played (local reset only); otherwise the next analyzed move creates a new session, the old session stays replayable via `GET /api/sessions/{id}` |
| 4 | Branch behavior | New move after going back discards the future variation (frontend and session truncation) |
| 5 | Navigation | Auto-analyzes un-analyzed positions; restores cached analyses when available |
| 6 | Level storage | On each analysis (with rating range), not on session |
| 7 | TTLs | Lichess 24 h, videos 7 d, Stockfish none (version-keyed), sessions none |
| 8 | Cache keys | Lichess: variant + moves + rating buckets; Stockfish: FEN + depth + engine version; videos: query |
| 9 | Degradation | Mongo outage never blocks analysis (direct calls, no cache writes); Lichess failure -> seed fallback |
| 10 | Only successful responses are cached | Lichess seed fallbacks and Stockfish `unavailable` results are never cached |
| 11 | Sequencing | RAG/Milvus after cache phases (deviation from `docs/PLAN.md`, captured in ADR 0005) |
| 12 | TODO.md | Temp working file, non-authoritative |

## Recommended Architecture

Use MongoDB for:

1. Session persistence and replay.
2. Lichess response caching.
3. Stockfish response caching.
4. Later, YouTube caching.

Keep responsibilities separate:

```text
Lichess       -> opening names, theory, statistics
Stockfish     -> out-of-theory evaluation
MongoDB       -> sessions and API caches
Milvus        -> pedagogical vector search
opening_book  -> offline fallback only
```

## 1. Frontend Navigation Model

The current `GameStateService` only stores one mutable `Chess` instance. It must become a timeline-based state model.

```text
initial position
  -> move 1
  -> move 2
  -> move 3
              ^
           cursor
```

Add to `GameStateService`:

- `currentIndex`
- `moveHistory`
- `snapshots`
- `goBack()`
- `goForward()`
- `canGoBack`
- `canGoForward`
- `reset()`
- `applyMove()`

Each snapshot should contain:

```ts
interface GameSnapshot {
  fen: string;
  pgn: string;
  moves: string[];
  legalDests: Dests;
  turn: 'white' | 'black';
  currentIndex: number;
}
```

For forward navigation, reconstruct the `Chess` position from the initial board and replay moves up to the requested index. This is safer than trying to maintain multiple mutable `Chess` instances.

Recommended behavior when playing a new move after going backward:

```text
1. e4 e5 Nf3
         ^
       back

Play d6

1. e4 e5 Nf3 d6
```

The old future branch is discarded. This matches normal chess analysis UI behavior.

## 2. Frontend Controls

Add left/right navigation controls near the move history:

- Previous position button.
- Next position button.
- Buttons disabled at the beginning/end of the timeline.
- Optional position indicator: `3 / 5`.

Keyboard behavior:

- `ArrowLeft`: go to previous position.
- `ArrowRight`: go to next position.
- Ignore keyboard shortcuts while focus is inside `input`, `textarea`, `select`, or `button`.
- Prevent browser horizontal scrolling when navigation is handled.

The board must be updated through the existing `setPosition()` method whenever the cursor changes.

Files affected:

- `frontend/src/app/services/game-state.ts`
- `frontend/src/app/services/game-state.spec.ts`
- `frontend/src/app/move-history/move-history.ts`
- `frontend/src/app/move-history/move-history.html`
- `frontend/src/app/app.ts`
- `frontend/src/app/app.html`

## 3. Analysis Behavior During Navigation

Analysis belongs to a position, not only to the latest move.

Use a frontend analysis map keyed by a stable position key:

```text
position key = normalized FEN + level + rating range
```

Behavior:

```text
User plays a new move
  -> request analysis
  -> display result
  -> save result in current session

User goes backward
  -> if analysis already exists locally, display it immediately
  -> otherwise request analysis

User goes forward
  -> restore the existing analysis if available
  -> otherwise request analysis
```

The backend cache remains necessary because the same FEN can be analyzed in a different browser session and the frontend cache disappears on refresh.

## 4. Session Lifecycle

### Application start

Create a session:

```http
POST /api/sessions
```

Response:

```json
{
  "id": "session-id",
  "started_at": "...",
  "status": "active"
}
```

The frontend stores only the session ID.

### New move

Persist the move:

```http
POST /api/sessions/{session_id}/moves
```

Payload:

```json
{
  "ply": 1,
  "uci": "e2e4",
  "san": "e4",
  "fen": "...",
  "pgn": "1. e4"
}
```

Only new moves should be persisted. Going backward or forward is navigation, not a new move.

### Analysis

Send the session ID with the analysis request:

```json
{
  "session_id": "session-id",
  "fen": "...",
  "pgn": "1. e4",
  "moves": ["e2e4"],
  "level": "debutant",
  "rating_min": 1000,
  "rating_max": 1400
}
```

After analysis, store the result in the session:

```http
POST /api/sessions/{session_id}/analyses
```

The analysis should be associated with the position key or normalized FEN.

### Reinitialise button

`Reinitialise` must create a new session, not merely clear the frontend:

```text
Click Reinitialise
  -> POST /api/sessions
  -> receive new session ID
  -> reset frontend timeline
  -> clear current analysis
  -> show initial board
```

The old session remains available for replay.

If session creation fails, do not silently overwrite the current session. Show an error and keep the current session active.

## 5. MongoDB Schema

### `sessions`

```json
{
  "_id": "...",
  "started_at": "...",
  "ended_at": null,
  "status": "active",
  "level": "debutant",
  "initial_fen": "starting-position",
  "moves": [
    {
      "ply": 1,
      "uci": "e2e4",
      "san": "e4",
      "fen": "...",
      "pgn": "1. e4",
      "created_at": "..."
    }
  ],
  "analyses": [
    {
      "position_key": "...",
      "fen": "...",
      "response": {},
      "created_at": "..."
    }
  ]
}
```

For the MVP, embedding moves and analyses inside the session is acceptable.

Indexes:

```text
sessions._id
sessions.started_at
sessions.status
```

### `lichess_cache`

```json
{
  "key": "normalized-moves|ratings",
  "payload": {},
  "source": "lichess-opening-explorer",
  "cached_at": "...",
  "expires_at": "..."
}
```

TTL: approximately 24 hours.

The cache key must include every parameter affecting the response:

- variant;
- move sequence;
- rating buckets;
- speeds, if used.

### `stockfish_cache`

```json
{
  "key": "normalized-fen|depth|engine-version",
  "payload": {},
  "cached_at": "..."
}
```

The key must include:

- normalized FEN;
- depth or time limit;
- engine version;
- relevant engine options.

Stockfish results can usually be retained longer than Lichess results. A change in Stockfish version must not reuse old results accidentally.

### `videos_cache`

```json
{
  "key": "normalized-query",
  "payload": [],
  "cached_at": "...",
  "expires_at": "..."
}
```

TTL: approximately 7 days.

## 6. Cache Lookup Flow

### Lichess

```text
Analyze position
  -> build Lichess cache key
  -> MongoDB find_one(key)
       |
       +-- hit: return cached payload
       |
       +-- miss:
              call Lichess
              validate response
              save response
              return response
```

If MongoDB is unavailable:

```text
Mongo read fails
  -> call Lichess directly
  -> do not save cache
  -> continue analysis
```

If Lichess fails, use the documented seed fallback and add `lichess_unavailable` to `fallbacks_used`.

### Stockfish

```text
Need Stockfish
  -> build FEN/depth/engine-version key
  -> MongoDB find_one(key)
       |
       +-- hit: return cached evaluation
       |
       +-- miss:
              run Stockfish
              save successful result
              return result
```

Do not cache an unavailable result as a successful evaluation. Temporary failure responses should either not be cached or have a very short TTL.

If MongoDB is unavailable, Stockfish still runs directly.

## 7. Backend Design

Add validated MongoDB configuration:

```toml
[mongodb]
uri = "mongodb://mongodb:27017"
database = "chess_agent"
connect_timeout_seconds = 1.5
cache_lichess_ttl_seconds = 86400
cache_videos_ttl_seconds = 604800
```

The URI is environment-specific and should normally be supplied through `.env` or Docker Compose.

Add service seams:

```text
backend/app/services/mongo.py
backend/app/services/session_store.py
backend/app/services/cache_store.py
```

Recommended interfaces:

```text
SessionStore
  create_session()
  append_move()
  save_analysis()
  get_session()
  end_session()

CacheStore
  get_lichess()
  set_lichess()
  get_stockfish()
  set_stockfish()
  get_videos()
  set_videos()
```

Initialize MongoDB once during application startup and close the client during shutdown. Do not instantiate a new client for every request.

## 8. API Endpoints

Add:

```http
POST /api/sessions
GET /api/sessions/{id}
POST /api/sessions/{id}/moves
POST /api/sessions/{id}/analyses
POST /api/sessions/{id}/end
```

Extend:

```http
POST /api/analyze-position
```

with:

```json
{
  "session_id": "..."
}
```

The existing response contract remains unchanged. Optional cache metadata can be exposed for the technical demonstration:

```json
{
  "cache": {
    "lichess": "hit",
    "stockfish": "miss"
  }
}
```

## 9. Docker Compose

Add MongoDB:

```yaml
mongodb:
  image: mongo:8
  volumes:
    - mongo_data:/data/db
  restart: unless-stopped
```

Configure the backend with:

```yaml
environment:
  MONGODB_URI: mongodb://mongodb:27017
  MONGODB_DATABASE: chess_agent
depends_on:
  - mongodb
```

`depends_on` only controls startup order. The backend must still tolerate MongoDB not being ready and retry or degrade gracefully.

## 10. Implementation Phases

### Phase 1: Frontend timeline — DONE

- [x] Refactor `GameStateService` to support a cursor (`currentIndex`, `line`, `goBack`, `goForward`, discard branch).
- [x] Add previous/next buttons with disabled states and a `n / total` indicator.
- [x] Add keyboard arrows (`ArrowLeft`/`ArrowRight`), ignored inside form controls, default prevented when handled.
- [x] Synchronize board, PGN, FEN, legal moves, and analysis.
- [x] Auto-analyze un-analyzed positions on navigation; restore cached analyses per position key; position 0 clears the analysis (the initial position is not analyzable under the current contract).
- [x] Unit tests for navigation, boundaries, and branching.

### Phase 2: Session API — DONE

- [x] MongoDB Compose service (`docker-compose.yml`, `mongo:8`).
- [x] `MongoSettings` (Pydantic, `[mongodb]` in `config.toml`, URI from `MONGODB_URI` env/.env only).
- [x] `pymongo` dependency; Mongo client lifecycle (lazy singleton, closed on FastAPI shutdown).
- [x] `sessions` persistence (`SessionStore`, embedded moves and analyses).
- [x] Session endpoints: `POST /api/sessions`, `GET /api/sessions/{id}`, `POST .../moves`, `POST .../analyses`, `POST .../end`.
- [x] Lazy creation: `POST /api/analyze-position` with optional `session_id` creates and returns the session on the first analyzed move.
- [x] Backend tests with a fake in-memory pymongo database.

### Phase 3: Move and analysis persistence — DONE

- [x] Persist moves only when new (navigation never mutates the session line; a branch truncates the discarded variation).
- [x] Persist analysis by position key (fen + level + rating buckets), level stored per analysis.
- [x] Session replay via `GET /api/sessions/{id}` tested.

### Phase 4: Lichess cache — DONE

- [x] Cache keys: variant + normalized UCI line + rating buckets; masters shares the collection with a distinct key prefix.
- [x] TTL index 24 h on `cached_at`; unique index on `key`.
- [x] Read cache before calling Lichess; store only successful responses; seed fallback preserved.
- [x] Cache hit/miss tests; fallback responses never cached.

### Phase 5: Stockfish cache — DONE

- [x] Cache key: EPD + depth + engine version (`engine_version` probes the binary once per process).
- [x] Only `status: ok` evaluations cached; `unavailable` never cached.
- [x] Tests for hit, miss, and Mongo outage.
- Note: `POST /api/stockfish/evaluate` stays uncached on purpose (raw engine probe); the analyze flow caches.

### Phase 6: Video cache — DEFERRED

- The YouTube API is not integrated yet: the current response is a deterministic local search-fallback link with no external call to cache.
- `CacheStore.get_videos`/`set_videos` are ready for the YouTube integration phase; TTL 7 d per ADR 0005.

### Phase 7: RAG/Milvus — PENDING

- Requires the framed research first (embedding model and pedagogical corpus are open zones per `docs/AGENT_CONTEXT.md`), then Milvus ingestion and retrieval in the analyze flow.
- Store only the resulting analysis in the session; never use MongoDB as the vector source.

## 11. Required Tests

### Frontend

- Previous button moves one position backward.
- Next button moves one position forward.
- Buttons disable at timeline boundaries.
- Left/right keyboard arrows work.
- Keyboard shortcuts do not trigger inside form controls.
- New move after going backward truncates the future branch.
- Reinitialise creates a clean new local session state.
- Existing analysis is restored when navigating.

### Backend

- Session creation.
- Move append.
- Analysis persistence.
- Session retrieval.
- Session ending.
- Lichess cache hit avoids the HTTP call.
- Lichess cache miss calls HTTP and stores the response.
- Lichess cache expiry triggers a new request.
- Stockfish cache hit avoids engine execution.
- Stockfish cache miss executes and stores the result.
- MongoDB outage does not prevent direct Lichess/Stockfish execution.
- Invalid cache payload is ignored safely.

## Recommended Order

```text
Frontend navigation
  -> MongoDB sessions
  -> Lichess cache
  -> Stockfish cache
  -> YouTube cache
  -> RAG/Milvus
```

The key MVP behavior is: when the user goes backward and then plays a different move, discard the old forward variation.
