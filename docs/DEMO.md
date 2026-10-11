# Demo Locale

Ce document sert de script court pour la video de demonstration. Il ne remplace pas le runbook RAG :
il indique quoi verifier avant d'enregistrer et quels points montrer.

## Prerequis

- Docker Compose v2.
- `.env` cree depuis `.env.example`.
- `NVIDIA_API_KEY` renseignee si `config.toml` garde `provider = "nvidia"`.
- Collection Milvus de `[milvus].collection` deja ingeree si le contexte RAG doit etre montre.
- Modele d'embeddings Ollama present : `qwen3-embedding:0.6b`.

## Preparation

```bash
cp .env.example .env
docker compose up -d mongodb milvus ollama
docker compose exec -T ollama ollama pull qwen3-embedding:0.6b
```

Si la collection RAG n'existe pas encore, suivre `docs/runbooks/RAG.md` avant la video. Une fois la
collection preparee et son nom reporte dans `config.toml`, verifier en lecture seule :

```bash
uv run python -m backend.app.ingestion.cli --no-ingest
```

Lancer ensuite la stack complete :

```bash
docker compose up -d --build
curl http://localhost:8000/health
```

Ouvrir `http://localhost:8080`.

## Cle NVIDIA Gratuite

Le provider coach par defaut est NVIDIA NIM. Pour une demo avec reponse LLM :

- creer un compte sur NVIDIA Build (`https://build.nvidia.com/`) ;
- ouvrir un modele NIM compatible OpenAI ;
- generer une API key dans l'espace utilisateur ;
- copier la cle dans `.env` : `NVIDIA_API_KEY=nvapi-...` ;
- relancer le backend si la cle a ete ajoutee apres le demarrage.

Si aucune cle n'est disponible, annoncer le mode degrade : l'Explorer, Stockfish, les videos fallback
et les sources restent visibles, mais le coach generatif peut passer en fallback.

## Scenario Video

1. Montrer la page d'accueil et le choix du niveau pedagogique.
2. Cliquer sur la demo `1. e4` ou jouer un premier coup legal.
3. Montrer l'ouverture identifiee, les coups recommandes et les statistiques Lichess.
4. Ajuster le filtre Elo et montrer que l'analyse se met a jour.
5. Ouvrir les onglets Sources et Videos pour montrer provenance, licence et fallback eventuel.
6. Demander une explication coach ou poser une question ciblee sur la position.
7. Montrer Stockfish apres un ecart ou une position moins theorique.
8. Jouer un coup recommande depuis l'interface pour prouver l'interaction echiquier/analyse.

## Points A Annoncer

- FastAPI orchestre les familles Explorer, RAG et Coach via LangGraph, avec des services metier
  imperatifs et testables.
- MongoDB stocke sessions, caches et `analysis_runs`.
- Milvus stocke uniquement les chunks pedagogiques vectorises.
- Stockfish est local et appele progressivement.
- YouTube a un fallback visible si la cle, le quota ou le service ne sont pas disponibles.
- Les limites connues du RAG sont documentees dans `docs/RAG-EVALUATION.md`.

## Verification Rapide

```bash
curl http://localhost:8000/health
docker compose ps
```

Si une brique externe echoue pendant la video, continuer la demo en montrant le fallback affiche dans
l'interface plutot que de masquer l'indisponibilite.
