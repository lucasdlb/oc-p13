# POC Agent d'ouvertures FFE

How-to humain pour lancer et verifier le POC local. L'index de la documentation est dans [`docs/README.md`](docs/README.md).

## Prerequis

- Docker Compose v2
- Python 3.12 et `uv`
- Node.js et npm pour le frontend
- Stockfish disponible dans le `PATH` ou dans `/usr/games/stockfish`

## Configuration

Les parametres non secrets sont dans `config.toml`. Ce fichier est obligatoire au demarrage : une
cle configurable absente doit faire echouer la validation plutot que revenir a un defaut cache dans le
code. Les secrets et valeurs liees a la machine restent dans `.env`.

```bash
cp .env.example .env
```

Renseigner uniquement les services utilises, par exemple:

```text
MONGODB_URI=mongodb://localhost:27017
MILVUS_URI=http://localhost:19530
OLLAMA_BASE_URL=http://localhost:11434
NVIDIA_API_KEY=nvapi-...
```

Le provider, le modele et l'URL du coach sont choisis dans `[llm]` et `[llm.providers.*]` de
`config.toml`. Le secret depend du provider choisi : `NVIDIA_API_KEY` ou `MISTRAL_API_KEY`.
Ollama ne demande pas de secret. Les anciennes variables generiques `LLM_PROVIDER`,
`LLM_BASE_URL` et `LLM_API_KEY` ne sont plus utilisees.

Par defaut, `config.toml` utilise le provider `nvidia`. Pour obtenir une cle gratuite de demo, creer
un compte sur NVIDIA Build (`https://build.nvidia.com/`), ouvrir un modele NIM compatible OpenAI,
puis generer une API key dans l'espace utilisateur. Copier la valeur dans `.env` sous
`NVIDIA_API_KEY=nvapi-...` avant de demarrer le backend. Sans cle valide, le coach LLM passera en
fallback ou restera indisponible selon le chemin appele; les donnees Explorer, Stockfish et les
fallbacks visibles restent demonstrables.

`OLLAMA_BASE_URL` est une exception volontaire : elle configure les embeddings Ollama et surcharge
`[llm.providers.ollama].base_url` quand `provider = "ollama"`, afin que Compose puisse pointer vers
`http://ollama:11434` sans modifier `config.toml`.

## Lancer La Stack

Mode demo Docker Compose complet :

```bash
docker compose up -d --build
```

En mode Compose, le backend force `MONGODB_URI=mongodb://mongodb:27017`,
`MILVUS_URI=http://milvus:19530` et `OLLAMA_BASE_URL=http://ollama:11434` pour joindre les services
internes Docker. Ces trois valeurs remplacent silencieusement celles de `.env`; utiliser les variables
de port de `.env.example` pour changer les ports exposes sur l'hote.

Puis ouvrir `http://localhost:8080`. Le frontend Docker est servi par nginx et relaie `/api` vers le
backend Docker.

Verifier l'API:

```bash
curl http://localhost:8000/health
```

Si le provider coach reste `nvidia` dans `config.toml`, renseigner `NVIDIA_API_KEY` dans `.env` avant
de demarrer le backend. Pour le RAG local, precharger le modele d'embeddings apres le demarrage
d'Ollama :

```bash
docker compose exec -T ollama ollama pull qwen3-embedding:0.6b
```

Mode GPU NVIDIA pour Ollama :

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

## Developpement Local En Parallele

La stack Docker utilise `localhost:8080` pour le frontend et `localhost:8000` pour l'API. Pour garder
une version locale divergente en parallele, lancer l'API locale sur `8001` :

```bash
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

Le frontend est lance depuis `frontend/`:

```bash
cd frontend
npm install
npm start
```

Puis ouvrir `http://localhost:4200`. Le proxy Angular de developpement cible `http://localhost:8001`,
ce qui evite de melanger par erreur le frontend local avec l'API Docker.

## Tests

Backend:

```bash
uv run pytest backend/tests
```

Frontend:

```bash
cd frontend
npm test -- --watch=false
```

## RAG

Les commandes d'ingestion, de benchmark et d'evaluation sont dans [`docs/runbooks/RAG.md`](docs/runbooks/RAG.md). Ne pas lancer l'ingestion pendant une demonstration.

L'arbre structure des ouvertures requis au runtime est versionne dans `backend/app/data/opening-tree/`.
Il permet au backend Docker de classifier les positions et de construire les plans RAG sans dependre de
`.scratch/`. Les passages pedagogiques restent servis par Milvus et doivent etre ingeres separement.

Le backend attend que la collection Milvus configuree dans `[milvus].collection` existe deja. Une
stack Compose fraiche lance Milvus, mais ne peuple pas automatiquement cette collection. Avant une
demo avec contexte RAG, preparer les donnees avec le runbook RAG, verifier la collection en lecture
seule, puis lancer la demo. Si la collection est absente ou incomplete, le RAG se degrade en fallback
visible et le coach dispose de moins de contexte pedagogique.

## Documentation

Commencer par [`docs/README.md`](docs/README.md), puis suivre le parcours correspondant a la question. Les regles de travail pour les agents sont dans [`AGENTS.md`](AGENTS.md) et [`docs/AGENT_CONTEXT.md`](docs/AGENT_CONTEXT.md).

Pour comprendre rapidement le projet:

- Architecture et contrats : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Script de demo : [`docs/DEMO.md`](docs/DEMO.md)
- Donnees, sources et licences : [`docs/data/`](docs/data/)
- Evaluation RAG : [`docs/RAG-EVALUATION.md`](docs/RAG-EVALUATION.md)
- Decisions : [`docs/adr/`](docs/adr/)
- Explainers HTML : [`docs/explainers/`](docs/explainers/)
