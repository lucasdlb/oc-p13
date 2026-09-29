# Architecture cible

L'architecture cible doit servir un POC local, demonstrable et contraint par les sources. Ce document decrit les composants techniques, les flux et les contrats d'API. Les details donnees, UX, planning et risques vivent dans leurs documents dedies.

Documents complementaires :

- `docs/DATA.md` : sources, MongoDB, Milvus, caches et matching.
- `docs/UX.md` : interface Angular, composants et layouts.
- `docs/PLAN.md` : ordre de livraison.
- `docs/RISKS.md` : risques, mitigations et escalades.

## Vue d'ensemble

```text
frontend Angular
+-- echiquier interactif
+-- selection du niveau pedagogique
+-- historique des coups
+-- panneau ouverture et coups recommandes
+-- panneau explication coach
+-- panneau statistiques Lichess
+-- panneau evaluation Stockfish
+-- panneau videos ou fallback YouTube

backend FastAPI
+-- API REST
+-- validation position avec python-chess
+-- orchestration LangGraph
+-- service openings MongoDB
+-- service Lichess
+-- service RAG Milvus
+-- service Stockfish
+-- service YouTube
+-- scripts d'ingestion et seed

data layer
+-- MongoDB : ouvertures, sessions, caches API
+-- Milvus : embeddings et chunks pedagogiques
+-- fichiers sources : chess-openings, corpus pedagogique valide

execution locale
+-- docker compose
+-- frontend
+-- backend
+-- mongodb
+-- milvus
+-- dependances Milvus requises
```

## Flux principal d'analyse

1. Le frontend envoie FEN, PGN, coups UCI et niveau pedagogique.
2. FastAPI valide la position avec `python-chess`.
3. LangGraph orchestre les noeuds d'analyse.
4. Le matching local cherche l'ouverture dans MongoDB.
5. Lichess fournit statistiques et coups populaires si disponibles.
6. Milvus fournit le contexte pedagogique pertinent.
7. Stockfish est appele si la theorie est absente, faible ou explicitement demandee.
8. YouTube renvoie des videos pertinentes ou un lien fallback.
9. Le coach produit une reponse contrainte par les resultats precedents.

## API minimale

```text
GET /health
POST /api/analyze-position
POST /api/stockfish/evaluate
GET /api/openings/{fen_or_epd}
GET /api/videos
POST /api/sessions
GET /api/sessions/{id}
```

Endpoint central :

```http
POST /api/analyze-position
```

Payload minimal :

```json
{
  "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
  "pgn": "1. e4",
  "moves": ["e2e4"],
  "level": "debutant"
}
```

Reponse minimale :

```json
{
  "opening": {
    "eco": "B00",
    "name": "King's Pawn Game",
    "matched": true,
    "source": "lichess-org/chess-openings"
  },
  "recommended_moves": [],
  "lichess_stats": {},
  "rag_context": [],
  "coach_explanation": "...",
  "stockfish": null,
  "videos": [],
  "fallbacks_used": []
}
```

## LangGraph cible

```text
Start
+-- normalize_position
+-- identify_opening
+-- fetch_lichess_stats
+-- retrieve_rag_context
+-- maybe_run_stockfish
+-- fetch_youtube_videos
+-- generate_coach_answer
+-- End
```

Les services doivent d'abord etre testables de maniere imperative. LangGraph orchestre ensuite des services deja stabilises, il ne doit pas devenir le lieu ou la logique metier est cachee.

## Sources de donnees

Les roles precis des sources, de MongoDB, de Milvus et des caches sont definis dans `docs/DATA.md`. L'architecture ne duplique pas ces schemas pour eviter deux sources de verite.

## Fallbacks autorises

| Cible | Fallback autorise | Condition d'activation | Impact |
| --- | --- | --- | --- |
| YouTube API | Lien de recherche YouTube pre-rempli | Cle absente, quota depasse ou delai integration | Videos non enrichies par metadata |
| Lichess API | Donnees seed ou cache MongoDB | API indisponible pendant demo | Stats possiblement non live |
| Milvus | Collection minimale seedee ou reponse RAG vide explicite | Probleme compose ou ingestion incomplete | Coach moins contextualise |
| LLM cloud | Provider compatible OpenAI alternatif ou mock coach source | Cle absente ou cout non valide | Reponse moins naturelle |
| Embeddings cloud | Modele local compact | Cle absente ou cout non valide | Setup local plus lourd |
| Librairie echiquier | Librairie Angular alternative validee | Incompatibilite version ou maintenance | UI adaptee mais Angular conserve |

Un fallback doit etre visible dans la reponse backend via `fallbacks_used` lorsque cela aide a comprendre la qualite de l'analyse.

## Recherche cadree requise

Avant implementation, les sujets suivants doivent etre recherches et valides par ADR ou note de decision :

- Provider LLM.
- Embeddings.
- Sources pedagogiques documentaires.
- Librairie d'echiquier Angular.

La recherche doit comparer au minimum : compatibilite locale, cout, qualite, effort d'integration, risques demo, licences ou conditions d'utilisation.

## Structure de depot cible

```text
backend/
+-- app/
|   +-- api/
|   +-- agents/
|   +-- core/
|   +-- ingestion/
|   +-- models/
|   +-- services/
|   +-- main.py
frontend/
+-- src/
data/
+-- raw/
+-- processed/
docs/
docker-compose.yml
```
