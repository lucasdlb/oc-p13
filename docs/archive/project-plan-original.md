> Statut documentaire : archive non maintenue.
>
> Ce fichier est l'ancien plan detaille initial. Son contenu utile a ete redistribue dans les documents specialises sous `docs/`. Ne pas l'utiliser comme source de verite operationnelle.

# Plan detaille du projet FFE

## Objectif

Developper en 2 semaines un POC d'agent intelligent pour accompagner les jeunes espoirs de la Federation Francaise des Echecs dans l'apprentissage des ouvertures.

Le POC doit etre executable localement avec `docker compose` et combiner :

- une interface Angular avec echiquier interactif ;
- un backend FastAPI ;
- un agent IA orchestre avec LangGraph ;
- Stockfish pour l'evaluation moteur ;
- les APIs Lichess pour les ouvertures et statistiques ;
- Milvus pour la recherche vectorielle ;
- MongoDB pour les donnees applicatives ;
- YouTube API pour proposer des videos explicatives.

## Perimetre fonctionnel

L'utilisateur joue des coups sur un echiquier. A chaque position, l'application doit :

- recuperer la position courante en FEN et l'historique en PGN/UCI ;
- identifier l'ouverture si elle est connue ;
- proposer les meilleurs coups issus de la theorie ;
- expliquer le contexte strategique de l'ouverture ;
- enrichir la reponse avec des statistiques Lichess ;
- proposer des videos YouTube pertinentes ;
- appeler Stockfish si la position sort des lignes connues ;
- conserver l'historique de session si necessaire.

## Architecture cible

```text
frontend Angular
+-- echiquier interactif
+-- historique des coups
+-- panneau coups recommandes
+-- panneau explication IA
+-- panneau statistiques Lichess
+-- panneau evaluation Stockfish
`-- panneau videos YouTube

backend FastAPI
+-- API REST
+-- agent LangGraph
+-- service Stockfish
+-- service Lichess
+-- service YouTube
+-- service RAG Milvus
+-- service MongoDB
`-- scripts d'ingestion

data layer
+-- MongoDB : sessions, ouvertures, cache API
+-- Milvus : embeddings et recherche semantique
`-- fichiers sources : Lichess openings, Wikibooks

services externes
+-- Lichess Opening Explorer
+-- YouTube Data API
`-- Wikibooks/Wikimedia API
```

## Structure de depot recommandee

```text
backend/
+-- app/
|   +-- api/
|   +-- agents/
|   +-- core/
|   +-- ingestion/
|   +-- models/
|   +-- services/
|   `-- main.py
frontend/
+-- src/
data/
+-- raw/
+-- processed/
docs/
docker-compose.yml
```

## Sources de donnees

### Source principale : lichess-org/chess-openings

Source recommandee pour le socle statique des ouvertures.

Avantages :

- donnees structurees ;
- licence CC0 / domaine public ;
- fichiers `a.tsv`, `b.tsv`, `c.tsv`, `d.tsv`, `e.tsv` ;
- champs utiles : `eco`, `name`, `pgn`, `uci`, `epd` ;
- ingestion simple dans MongoDB et Milvus ;
- donnees proches de l'ecosysteme Lichess.

Usage prevu :

- stocker les ouvertures dans MongoDB ;
- indexer les descriptions generees dans Milvus ;
- matcher les positions par ligne UCI/PGN ou EPD.

### Source pedagogique : Wikibooks Chess Opening Theory

Source recommandee pour enrichir les explications textuelles.

Avantages :

- contenu pedagogique riche ;
- structure par lignes d'ouverture ;
- accessible via l'ecosysteme Wikimedia ;
- plus adapte au RAG textuel que Wikichess pour un POC.

Usage prevu :

- recuperer un sous-ensemble de pages utiles ;
- nettoyer le texte ;
- chunker par page ou par section ;
- indexer dans Milvus avec metadata `source`, `url`, `title`, `opening_line`.

### Source live : Lichess Opening Explorer

Source recommandee pour les statistiques en temps reel.

Usage prevu :

- recuperer les coups populaires d'une position ;
- afficher nombre de parties, taux de victoire, nulles, defaites ;
- ne pas stocker massivement ces donnees dans Milvus ;
- utiliser MongoDB comme cache pour limiter les appels repetes.

### Wikichess / FICGS

Le cahier des charges mentionne Wikichess, mais accepte aussi toutes sources pertinentes.

Position recommandee : ne pas en faire la source principale du POC.

Raisons :

- HTML ancien et fragile a parser ;
- structure moins propre que Lichess openings ;
- conditions de reutilisation/licence a verifier ;
- qualite editoriale heterogene ;
- risque de perdre du temps sur du scraping au lieu de livrer le POC.

Phrase client possible :

> Le cahier des charges mentionne Wikichess, mais autorise aussi toutes sources pertinentes. Pour fiabiliser le POC, nous privilegions `lichess-org/chess-openings` sous licence CC0 et Wikibooks Chess Opening Theory, plus structures et plus surs a integrer. Wikichess pourra etre etudie comme source complementaire apres verification de ses conditions d'usage.

## Stack technique recommandee

### Frontend

Choix recommande : Angular.

Librairies possibles :

- `ngx-chessboard` ;
- `material-chessboard` du centre OpenClassrooms ;
- Angular Material pour composants standards ;
- Tailwind CSS si l'equipe veut aller vite sur le style.

Alternatives :

- React avec `react-chessboard`, plus rapide si l'equipe maitrise React, mais moins conforme au cahier des charges ;
- Vue, non recommande ici car non demande ;
- echiquier custom, a eviter pour un POC court.

### Backend

Choix recommande : Python 3.12 + FastAPI.

Librairies utiles :

- FastAPI ;
- Pydantic ;
- LangGraph ;
- LangChain si utile pour embeddings/RAG ;
- `python-chess` ;
- `pymilvus` ;
- `pymongo` ou Motor ;
- `httpx` pour APIs externes.

Alternatives :

- Flask, plus simple mais moins adapte aux APIs typees modernes ;
- Django, trop lourd pour ce POC ;
- Node/NestJS, possible mais moins coherent avec Stockfish, LangGraph Python et data pipeline.

### Agent IA

Choix recommande : LangGraph.

Raisons :

- conforme au cahier des charges ;
- controle explicite des etapes ;
- facilite l'orchestration entre RAG, Lichess, YouTube et Stockfish.

Alternatives :

- pipeline imperatif Python pour demarrer vite ;
- LangChain Agent classique, plus simple mais moins controlable ;
- CrewAI/AutoGen, trop lourd pour le besoin.

Approche pragmatique : developper d'abord les services de maniere imperative, puis les brancher dans LangGraph.

### Base vectorielle

Choix demande : Milvus.

Usage :

- indexer les documents d'ouverture ;
- rechercher le contexte pedagogique pertinent ;
- alimenter la reponse du coach IA.

Alternatives :

- Qdrant, plus simple a exploiter localement ;
- Chroma, rapide pour prototype mais moins robuste ;
- FAISS, utile localement mais pas une base vectorielle serveur.

Pour respecter le cahier des charges, Milvus reste le choix cible.

### Base applicative

Choix demande : MongoDB.

Collections recommandees :

```text
openings
sessions
analysis_cache
videos_cache
```

Alternatives :

- PostgreSQL, meilleur pour donnees relationnelles mais non demande ;
- SQLite, suffisant pour prototype local mais moins credible pour ce livrable.

### Embeddings

Options :

- OpenAI embeddings : simple, performant, depend d'une cle API ;
- `sentence-transformers` : local, sans cout API, plus lourd a packager ;
- `BAAI/bge-small-en-v1.5` : bon compromis pour anglais ;
- `bge-m3` : meilleur multilingue, plus lourd.

Recommandation POC : OpenAI embeddings si une cle est disponible, sinon `sentence-transformers` avec un modele compact.

### LLM

Options :

- OpenAI ou API compatible OpenAI : recommande pour fiabiliser la demo ;
- Anthropic, Mistral, Gemini : possibles via abstraction provider ;
- Ollama local : utile sans cle API, mais qualite et latence plus variables.

Recommandation POC : provider cloud compatible OpenAI, avec une abstraction simple pour pouvoir changer ensuite.

### Stockfish

Choix recommande : binaire Stockfish local appele par `python-chess.engine`.

Alternatives :

- package PyPI `stockfish`, simple mais dependant du binaire ;
- Stockfish en service Docker separe ;
- Stockfish WASM cote frontend, moins propre pour centraliser l'analyse.

### Deploiement local

Choix recommande : `docker compose`.

Services :

```text
frontend
backend
mongodb
milvus
etcd
minio
```

Stockfish peut etre installe directement dans l'image backend.

Variables d'environnement :

```text
OPENAI_API_KEY
YOUTUBE_API_KEY
LICHESS_TOKEN
MONGODB_URI
MILVUS_HOST
MILVUS_PORT
EMBEDDING_PROVIDER
```

## API backend proposee

Endpoints minimum :

```text
GET /health
POST /api/analyze-position
POST /api/stockfish/evaluate
GET /api/openings/{fen}
GET /api/videos
POST /api/sessions
GET /api/sessions/{id}
```

Endpoint central :

```http
POST /api/analyze-position
```

Payload exemple :

```json
{
  "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
  "pgn": "1. e4",
  "moves": ["e2e4"],
  "level": "beginner"
}
```

Reponse exemple :

```json
{
  "opening": {
    "eco": "B00",
    "name": "King's Pawn Game",
    "matched": true
  },
  "recommended_moves": [],
  "lichess_stats": {},
  "rag_context": [],
  "coach_explanation": "...",
  "stockfish": {},
  "videos": []
}
```

## Modele de donnees

### Collection MongoDB `openings`

```json
{
  "eco": "C20",
  "name": "King's Pawn Game",
  "pgn": "1. e4 e5",
  "uci": "e2e4 e7e5",
  "epd": "...",
  "source": "lichess-org/chess-openings"
}
```

### Collection MongoDB `sessions`

```json
{
  "created_at": "2026-09-29T00:00:00Z",
  "moves": [],
  "positions": [],
  "analyses": []
}
```

### Collection Milvus `chess_knowledge`

Champs recommandes :

```text
id
vector
text
source
url
opening_name
pgn
fen_or_epd
```

## Graphe LangGraph recommande

```text
Start
+-- normalize_position
+-- identify_opening
+-- fetch_lichess_stats
+-- retrieve_rag_context
+-- maybe_run_stockfish
+-- fetch_youtube_videos
+-- generate_coach_answer
`-- End
```

Description des noeuds :

- `normalize_position` valide FEN, PGN et coups avec `python-chess` ;
- `identify_opening` cherche un match exact dans MongoDB ;
- `fetch_lichess_stats` recupere les statistiques live ;
- `retrieve_rag_context` interroge Milvus ;
- `maybe_run_stockfish` lance Stockfish si la position sort de la theorie ;
- `fetch_youtube_videos` recupere des videos explicatives ;
- `generate_coach_answer` produit une reponse pedagogique.

## Strategie Stockfish

Stockfish doit etre appele si :

- aucune ouverture n'est identifiee ;
- Lichess retourne peu de parties ;
- le coup joue n'apparait pas dans les coups theoriques ;
- l'utilisateur demande explicitement une evaluation moteur.

Reponse type :

```json
{
  "best_move": "g1f3",
  "score_cp": 35,
  "depth": 12,
  "principal_variation": ["g1f3", "b8c6", "f1b5"]
}
```

## Strategie YouTube

Recherche recommandee :

```text
"{opening_name} chess opening explanation"
"{opening_name} chess opening beginner"
"{eco} {opening_name} chess"
```

Resultats a afficher :

- titre ;
- URL ;
- miniature ;
- chaine ;
- duree si disponible.

Fallback si la cle API n'est pas disponible : generer un lien de recherche YouTube pre-rempli.

## Interface Angular

Composants recommandes :

```text
AppComponent
ChessboardComponent
MoveHistoryComponent
AnalysisPanelComponent
RecommendedMovesComponent
OpeningInfoComponent
StockfishPanelComponent
VideosPanelComponent
```

Flux utilisateur :

- l'utilisateur joue un coup ;
- le frontend met a jour FEN/PGN ;
- le frontend appelle `POST /api/analyze-position` ;
- l'interface affiche un etat de chargement ;
- l'analyse apparait avec ouverture, coups, explication, stats et videos.

Layout recommande :

```text
Desktop
+-- colonne gauche : echiquier + historique
`-- colonne droite : analyse + stats + videos

Mobile
+-- echiquier
+-- coup recommande
+-- explication
+-- stats
`-- videos
```

## Planning 2 semaines

### Jour 1

- cadrage technique ;
- validation du MVP ;
- creation structure repo ;
- squelette FastAPI ;
- squelette Angular ;
- `docker compose` minimal.

### Jour 2

- echiquier Angular ;
- generation FEN/PGN ;
- endpoint `/health` ;
- endpoint `/api/analyze-position` mocke.

### Jour 3

- ingestion `lichess-org/chess-openings` ;
- stockage MongoDB ;
- premier matching d'ouverture.

### Jour 4

- installation Milvus ;
- generation embeddings ;
- indexation des documents d'ouverture.

### Jour 5

- ingestion Wikibooks limitee aux ouvertures principales ;
- nettoyage texte ;
- recherche RAG Milvus.

### Jour 6

- integration Lichess Opening Explorer ;
- affichage statistiques ;
- cache MongoDB.

### Jour 7

- integration Stockfish ;
- fallback hors theorie ;
- format de reponse stabilise.

### Jour 8

- creation du graphe LangGraph ;
- orchestration des services ;
- prompt coach pedagogique.

### Jour 9

- integration YouTube API ;
- affichage videos ;
- fallback lien de recherche.

### Jour 10

- amelioration UI ;
- responsive desktop/mobile ;
- panneaux analyse, stats, videos.

### Jour 11

- `docker compose` complet ;
- variables d'environnement ;
- script d'ingestion executable.

### Jour 12

- tests backend ;
- tests frontend de base ;
- tests integration.

### Jour 13

- preparation demo ;
- donnees de seed ;
- documentation d'execution ;
- corrections UX.

### Jour 14

- repetition demo ;
- bugfix final ;
- livraison.

## Priorites d'implementation

Ordre recommande :

1. Backend analyse position mocke.
2. Front echiquier connecte.
3. Matching local des ouvertures.
4. Statistiques Lichess.
5. Stockfish.
6. RAG Milvus.
7. LangGraph.
8. YouTube.
9. Docker compose complet.
10. Polish demo.

## Risques et mitigations

| Risque | Mitigation |
| --- | --- |
| Milvus prend trop de temps a configurer | partir du docker compose officiel, garder Qdrant comme fallback interne |
| Wikibooks trop gros a ingerer | limiter aux ouvertures principales pour le POC |
| Cle YouTube absente ou quota depasse | fallback vers liens de recherche YouTube |
| Stockfish difficile a packager | installer le binaire dans l'image backend et utiliser `python-chess.engine` |
| LangGraph complexifie trop le developpement | stabiliser d'abord les services puis les brancher dans le graphe |
| Reponses IA hallucinees | separer donnees structurees et texte genere, fournir le contexte RAG explicitement |

## Scenarios de demo

### Scenario 1 : ouverture connue

- jouer `1. e4` ;
- afficher l'ouverture identifiee ;
- afficher les coups candidats ;
- expliquer les idees principales ;
- proposer une video.

### Scenario 2 : ligne theorique

- jouer `1. e4 e5 2. Nf3 Nc6 3. Bb5` ;
- identifier l'Espagnole / Ruy Lopez ;
- expliquer le plan blanc ;
- afficher les stats Lichess.

### Scenario 3 : sortie de theorie

- jouer un coup marginal ou faible ;
- declencher Stockfish ;
- expliquer pourquoi la position sort des lignes connues ;
- proposer un plan de correction.

### Scenario 4 : preuve technique

- montrer l'application lancee via `docker compose` ;
- montrer MongoDB et Milvus actifs ;
- montrer l'ingestion des sources ;
- montrer l'appel a Lichess et YouTube.

## Questions a trancher avant implementation

1. Utiliser un LLM cloud ou local ?
2. Utiliser des embeddings cloud ou locaux ?
3. Une cle YouTube API est-elle disponible ?
4. Une cle Lichess est-elle necessaire ou l'API publique suffit-elle ?
5. Le frontend doit-il absolument etre Angular ou peut-il y avoir une alternative ?
6. Le POC doit-il privilegier la qualite de demo ou l'exhaustivite technique ?

## Recommandation finale

Pour tenir les delais, privilegier cette combinaison :

- Angular pour le frontend ;
- FastAPI pour le backend ;
- LangGraph pour l'orchestration ;
- MongoDB pour sessions, caches et ouvertures ;
- Milvus pour le RAG ;
- Stockfish local dans le backend ;
- `lichess-org/chess-openings` comme source principale ;
- Wikibooks comme source pedagogique ;
- Lichess Opening Explorer en live ;
- YouTube API avec fallback lien de recherche.
