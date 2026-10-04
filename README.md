# POC Agent d'ouvertures FFE

Ce depot contient le POC d'un agent intelligent pour accompagner les jeunes espoirs de la Federation Francaise des Echecs dans l'apprentissage des ouvertures.

## Documentation

- [Contexte agentique de reference](docs/AGENT_CONTEXT.md)
- [MVP et criteres d'acceptation](docs/MVP.md)
- [Architecture cible](docs/ARCHITECTURE.md)
- [Donnees et sources](docs/DATA.md)
- [Runbook RAG (CPU, GPU et ingestion)](docs/RAG-RUNBOOK.md)
- [Schemas des APIs externes (Lichess, Stockfish)](docs/DATA-SCHEMAS.md)
- [UX Angular](docs/UX.md)
- [Plan de livraison](docs/PLAN.md)
- [Risques et mitigations](docs/RISKS.md)
- [Cahier des charges](docs/PROJECT.md)

Les agents doivent commencer par `docs/AGENT_CONTEXT.md` avant toute proposition ou implementation. Les decisions structurantes sont documentees dans `docs/adr/`. Les anciens plans non maintenus sont conserves dans `docs/archive/`.

## Objectif du POC

L'application doit proposer une interface Angular avec echiquier interactif et un backend FastAPI capable d'analyser une position d'echecs avec :

- identification de la position en FEN ;
- donnees d'ouvertures Lichess ;
- recherche vectorielle Milvus ;
- stockage MongoDB ;
- orchestration LangGraph ;
- evaluation Stockfish hors theorie ;
- videos YouTube pertinentes.

## Stack cible

- Frontend : Angular, `@lichess-org/chessground` et `chess.js`
- Backend : FastAPI, Python 3.12, LangGraph
- Donnees : MongoDB, Milvus
- Moteur : Stockfish
- APIs : Lichess, YouTube
- Execution locale : `docker compose`

## Configuration locale

Les parametres non secrets vivent dans `config.toml`. Lichess Opening Explorer peut etre active pour tenter les statistiques live, avec fallback seed si le service refuse ou ne repond pas :

```toml
[lichess]
enabled = true
base_url = "https://explorer.lichess.org"
timeout_seconds = 2.0
```

Le token Lichess est un secret et doit rester dans `.env`, jamais dans `config.toml` :

```bash
cp .env.example .env
```

Puis renseigner :

```text
LICHESS_TOKEN=<votre-token-lichess>
```

Generer le token depuis `https://lichess.org/account/oauth/token`. D'apres la specification OpenAPI Lichess, Opening Explorer utilise OAuth2 sans scope specifique pour `/lichess` et `/masters`.

Quand `enabled = false`, quand `LICHESS_TOKEN` manque, ou quand Lichess est indisponible, non autorise, invalide ou vide, le backend renvoie les statistiques seed `seed-lichess-cache` et expose le fallback dans `fallbacks_used`.

Stockfish est appele pour une position inconnue ou lorsque les donnees d'ouverture sont trop faibles. Le binaire est configure dans `[stockfish]` (`binary`, `depth`, `timeout_seconds`) et doit etre disponible dans le `PATH`. Si le binaire manque, l'API renvoie une evaluation `unavailable` avec sa raison au lieu de faire echouer l'analyse.

MongoDB stocke les sessions de demonstration et les caches Lichess/Stockfish (ADR 0005). Le service se lance avec `docker compose up -d mongodb`. L'URI de connexion est specifique a l'environnement et vit dans `.env` :

```text
MONGODB_URI=mongodb://localhost:27017
```

Si MongoDB est absent ou indisponible, l'analyse continue sans persistance et sans cache, et la reponse expose le fallback `mongo_sessions_unavailable` ainsi que les statuts de cache (`hit`, `miss`, `skipped`) dans le champ `cache`. Les autres parametres (`database`, TTLs, timeouts) vivent dans `[mongodb]` dans `config.toml`.

Sur Ubuntu, installer le moteur avec `sudo apt install stockfish`. Le service detecte aussi l'emplacement standard `/usr/games/stockfish` si ce dossier n'est pas present dans le `PATH`.

Redemarrer FastAPI apres modification de `.env` ou `config.toml`, car les settings sont charges au demarrage.

## RAG, Milvus et Ollama

La recherche vectorielle utilise Milvus, les embeddings et le LLM du coach passent par Ollama (ADR 0006). Les services se lancent avec :

```bash
docker compose up -d mongodb ollama milvus
docker compose exec ollama ollama pull qwen3-embedding:0.6b
```

Les parametres non secrets vivent dans `config.toml` (`[embeddings]`, `[milvus]`, `[rag]`, `[llm]`). Les valeurs specifiques a l'environnement vivent dans `.env`, jamais dans `config.toml` :

```text
MILVUS_URI=http://localhost:19530
OLLAMA_BASE_URL=http://localhost:11434
```

En dev et dans les tests, `MILVUS_URI` peut pointer vers un fichier local (Milvus Lite), par exemple `.scratch/rag/milvus.db`. **Cible** (non encore cablee, phase 3) : si Milvus ou Ollama est indisponible, l'analyse ne doit jamais echouer, elle renvoie un `rag_context` vide explicite et un coach deterministe, traces dans `fallbacks_used`.

### Harness R&D (phase R)

Le harness de la phase R vit dans `experiments/rag/` (versionne) ; les corpus bruts et les bases Milvus Lite vivent dans `.scratch/rag/` (ignore par git).

Le corpus **vectoriel est de la prose seule** (pages Wikibooks). `lichess-org/chess-openings` est une donnee structuree (matching / jointure `eco_code`) et n'est **pas** ingeree dans Milvus (ADR 0006 revise).

```bash
# 1. Recuperer le corpus cure (chess-openings pour le structure + pages Wikibooks pour la prose)
uv run python -m experiments.rag.fetch_corpus

# 2. Mesurer une configuration (page ou section)
uv run python -m experiments.rag.run --config experiments/rag/configs/section.json

# Re-scorer sans re-embedder (la collection versionnee doit exister et correspondre)
uv run python -m experiments.rag.run --config experiments/rag/configs/section.json --no-ingest
```

Chaque run ecrit `experiments/rag/runs/<timestamp>_<nom>/{effective-config.json,metrics.json,run.json}` avec la config effective validee, le digest du modele, les hashes corpus / golden set / jugements, le sha git et les hits retrouves. Les collections sont versionnees par empreinte et jamais supprimees avant validation de la remplacante. La pertinence est jugee au passage (`experiments/rag/judgments.json`) ; les requetes hors corpus et hors theorie sont rapportees separement. Resultats et limites : `docs/adr/0006-rag-milvus-and-embeddings.md`.

Note : le branchement de `RagService` et `CoachService` dans `/api/analyze-position` (phases 3 et 4) reste a faire ; le backend expose deja les seams (`backend/app/services/embeddings.py`, `llm.py`, `milvus.py`) et le schema commun (`backend/app/models/knowledge.py`).
