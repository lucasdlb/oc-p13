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
5. Lichess fournit statistiques et coups populaires filtres par plage de niveau joueur si disponibles.
5a. Masters fournit une vue theorique separee des coups issus de parties de maitres.
6. Le service d'ouvertures construit une fenetre locale dans l'arbre `chess-openings` : noeud courant, parent immediat, enfants directs et, au plus, petits-enfants pour ranking interne.
7. Milvus fournit le contexte pedagogique pertinent : prose du noeud courant en priorite, prose des enfants directs seulement comme explication conditionnelle de suites possibles.
8. Stockfish est appele si la theorie est absente, si aucun coup candidat pertinent ne reste, ou si la confiance statistique Lichess est faible.
9. YouTube renvoie des videos pertinentes ou un lien fallback.
10. Le coach produit une reponse contrainte par les resultats precedents.

Le coach recoit le contexte en sections separees : position courante, suites possibles directes, prose principale, puis prose sur suites possibles. Une prose issue d'un enfant direct doit rester conditionnelle et attachee a son `entry_move`; elle ne peut pas etre formulee comme etat courant tant que le coup correspondant n'a pas ete joue.

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
  "masters_moves": [],
  "lichess_stats": {},
  "source_confidence": {},
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

Evolution cible (ADR 0006) : d'abord un **DAG deterministe** dont chaque noeud appelle son outil par defaut, puis des conditions documentees (profondeur de partie, niveau pedagogique) pour des appels d'outils selectifs, et a terme un routage agentique. `RagService` et `CoachService` ne doivent pas importer `langgraph`.

Milvus standalone (phase 1) : le store est servi soit par **Milvus Lite** (fichier local, dev/tests/harness), soit par **Milvus Standalone** (`docker-compose.yml`) via `MILVUS_URI`. La compose officielle de Milvus reference `minio/minio`, dont les images Docker Hub ont ete retirees ; la pile utilise donc `bitnamilegacy/minio` (meme API S3), et propage `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` a Milvus (`MINIO_ACCESS_KEY_ID` / `MINIO_SECRET_ACCESS_KEY`) pour que des credentials surcharges restent coherents entre les deux services. Ollama (embeddings `qwen3-embedding:0.6b`, LLM du coach) tourne dans la meme compose avec un volume de cache `ollama_models`. Milvus ne contient que de la prose pedagogique ; `chess-openings` est une donnee structuree hors Milvus (ADR 0006).

Retrieval d'ouverture cible : `chess-openings` est l'arbre deterministe de lignes et de suites candidates ; Milvus est le retrieval de prose pedagogique. Le RAG global assemble les deux sans les confondre. Le retrieval Milvus ne doit pas elargir a tous les descendants d'une ouverture ; il utilise une fenetre locale, un budget separe pour les enfants directs et une penalite par distance dans l'arbre pour eviter la pollution par des variantes trop profondes.

Routeur d'intention cible : la classification floue de la question utilisateur peut etre confiee a un modele de decision structuree de type **Jev / System One** (TypeSafe AI) plutot qu'a un LLM generatif. Le routeur ne genere pas la reponse coach et ne choisit pas librement les sources critiques : il retourne une intention typee, des probabilites et une confidence. Le code backend transforme ensuite cette decision en `retrieval_plan` deterministe (`tree_context`, `current_prose`, `candidate_prose`, `general_principles`, `stockfish`). En cas de confidence faible ou d'indisponibilite du routeur, le systeme revient a un plan conservateur rule-based : arbre + prose du noeud courant, sans prose enfant sauf coup explicitement demande. Toute integration Jev reste une dependance externe a valider par ADR/recherche avant implementation.

## Sources de donnees

Les roles precis des sources, de MongoDB, de Milvus et des caches sont definis dans `docs/DATA.md`. L'architecture ne duplique pas ces schemas pour eviter deux sources de verite.

## Fallbacks autorises

| Cible | Fallback autorise | Condition d'activation | Impact |
| --- | --- | --- | --- |
| YouTube API | Lien de recherche YouTube pre-rempli | Cle absente, quota depasse ou delai integration | Videos non enrichies par metadata |
| Lichess API | Donnees seed ou cache MongoDB | `lichess.enabled = false`, `LICHESS_TOKEN` absent, API indisponible, acces non autorise, timeout ou reponse invalide | Stats possiblement non live |
| Milvus | Collection minimale seedee ou reponse RAG vide explicite | Probleme compose ou ingestion incomplete | Coach moins contextualise |
| LLM cloud | Provider compatible OpenAI alternatif ou mock coach source | Cle absente ou cout non valide | Reponse moins naturelle |
| Embeddings local (`Qwen3-Embedding-0.6B`) | Modele local plus leger (`intfloat/multilingual-e5-base`) | Ressources insuffisantes, latence demo trop haute ou echec de telechargement | Qualite de retrieval possiblement moindre |
| Ollama (embeddings + LLM) | `rag_context` vide explicite / coach deterministe (template) | Service compose indisponible, modele non telecharge ou timeout | Analyse jamais en echec, contexte et synthese appauvris |
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
