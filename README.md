# POC Agent d'ouvertures FFE

How-to humain pour lancer et verifier le POC local. L'index de la documentation est dans [`docs/README.md`](docs/README.md).

## Prerequis

- Docker Compose v2
- Python 3.12 et `uv`
- Node.js et npm pour le frontend
- Stockfish disponible dans le `PATH` ou dans `/usr/games/stockfish`

## Configuration

Les parametres non secrets sont dans `config.toml`. Les secrets et valeurs liees a la machine restent dans `.env`.

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

## Lancer La Stack

```bash
docker compose up -d
```

Verifier l'API:

```bash
curl http://localhost:8000/health
```

Le frontend est lance depuis `frontend/`:

```bash
cd frontend
npm install
npm start
```

Puis ouvrir `http://localhost:4200`.

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

## Documentation

Commencer par [`docs/README.md`](docs/README.md), puis suivre le parcours correspondant a la question. Les regles de travail pour les agents sont dans [`AGENTS.md`](AGENTS.md) et [`docs/AGENT_CONTEXT.md`](docs/AGENT_CONTEXT.md).

Pour comprendre rapidement le projet:

- Architecture et contrats : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Donnees, sources et licences : [`docs/data/`](docs/data/)
- Evaluation RAG : [`docs/RAG-EVALUATION.md`](docs/RAG-EVALUATION.md)
- Decisions : [`docs/adr/`](docs/adr/)
- Explainers HTML : [`docs/explainers/`](docs/explainers/)
