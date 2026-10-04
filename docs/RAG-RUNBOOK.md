# Runbook RAG

Ce runbook exploite le corpus Wikibooks cure actuel. L'ingestion est une commande offline : elle ne
fait pas partie du demarrage FastAPI et ne doit jamais etre lancee pendant une partie.

## Prerequis

- Docker Compose v2, Python 3.12 et `uv`.
- Pour NVIDIA : pilote hote compatible et NVIDIA Container Toolkit/CDI configure pour Docker.
- `.env` peut definir `MILVUS_URI` et `OLLAMA_BASE_URL`; les parametres non secrets restent dans
  `config.toml`.

Verifier les configurations sans demarrer de service :

```bash
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.gpu.yml config --quiet
```

## Demarrage CPU

```bash
docker compose up -d ollama milvus
docker compose exec -T ollama ollama pull qwen3-embedding:0.6b
```

## Demarrage NVIDIA

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gpu.yml \
  up -d ollama milvus
docker compose exec -T ollama ollama pull qwen3-embedding:0.6b
```

L'override ne change que l'allocation GPU d'Ollama. Si Docker signale qu'aucun driver/CDI NVIDIA
n'est disponible, arreter ici : configurer NVIDIA Container Toolkit est une operation systeme qui
requiert une autorisation explicite.

Les deux fichiers Compose sont fusionnes et pilotent le meme conteneur `p13-ollama`; ils ne lancent
pas deux Ollama en parallele. Le volume `ollama_models` est conserve lors du changement de mode. Pour
revenir explicitement au CPU :

```bash
docker compose up -d --force-recreate ollama
```

Faire une requete d'embedding ou une ingestion, puis verifier le runtime reel :

```bash
docker compose exec -T ollama ollama ps
```

La colonne `PROCESSOR` doit mentionner le GPU, et non `100% CPU`. Une Compose valide ou une RTX
visible sur l'hote ne prouve pas l'usage GPU. `run.json.embedding_runtime` doit confirmer le meme
fait; `unknown` signifie que la preuve manque.

## Corpus actuel

```bash
uv run python -m experiments.rag.fetch_corpus
```

La commande doit annoncer cinq TSV `chess-openings` et treize pages Wikibooks presentes ou mises en
cache. Seules les pages Wikibooks sont nettoyees et vectorisees; les TSV restent des donnees
structurees. La CLI refuse un corpus vide et le nettoyage rejette toute page sans prose exploitable
ou contenant encore du markup interdit.

Ce corpus cure de treize pages est celui que sert la demo (`config.toml`). Le corpus complet vit
cote a cote, avec son propre manifeste versionne :

```bash
uv run python -m experiments.rag.clean_report
uv run python -m experiments.rag.build_snapshot --force
```

`clean_report` relit `wikibooks-full/manifest.json`, applique les regles de classification et le
mapper d'alias d'ouverture, et reecrit `wikibooks-clean/` ; `build_snapshot` produit
`wikibooks-snapshot/` (immuable, reference par hash et lie au jeu d'evaluation Eval V2). Un
rebuild change le hash du snapshot, donc le nom de la collection cible.

## Ingestion

Ingestion complete dans une nouvelle cible deterministe :

```bash
uv run python -m backend.app.ingestion.cli --ingest-mode full
```

Une cible `full` deja peuplee est refusee, jamais supprimee. Pour synchroniser ou reprendre la meme
cible :

```bash
uv run python -m backend.app.ingestion.cli --ingest-mode incremental
uv run python -m backend.app.ingestion.cli --resume
```

Pour reutiliser un predecesseur compatible, donner son nom exact; aucun nom n'est devine :

```bash
uv run python -m backend.app.ingestion.cli \
  --ingest-mode incremental \
  --collection NOUVELLE_COLLECTION \
  --reuse-from-collection COLLECTION_PRECEDENTE
```

La compatibilite exige schema, modele et digest, dimension, metrique et format vectoriel identiques.
Les metadonnees courantes sont reecrites avec les vecteurs reutilises. Une panne laisse la cible
partielle reprenable avec `--resume`; le predecesseur n'est jamais modifie.

Valider en lecture seule une collection complete sans embedding :

```bash
uv run python -m backend.app.ingestion.cli --no-ingest
```

Milvus Lite verrouille exclusivement son fichier : ne pas lancer deux commandes simultanees contre
le meme fichier `.db`.

## Benchmark

Le harness appelle le meme pipeline d'ingestion :

```bash
uv run python -m experiments.rag.run \
  --config experiments/rag/configs/section.json \
  --ingest-mode incremental

uv run python -m experiments.rag.run \
  --config experiments/rag/configs/section.json \
  --no-ingest
```

`IngestReport` distingue `already_present`, `reused`, `embedded`, `inserted` et `final_count`, avec
les temps d'inspection, reutilisation, embedding, ecriture et verification. Dans `run.json`, verifier
le digest, `embedding_runtime`, `embedding_runtime_scope`, le hash du snapshot, le mode, le rapport
et la collection. Si le scope vaut `query_embeddings_only`, le runtime observe ne prouve pas le
materiel qui avait produit les vecteurs deja presents ou reutilises. Dans
`metrics.json`, lire les metriques de ranking et les latences; elles ne prouvent pas a elles seules
la qualite ni l'usage GPU.

Ce harness fait une recherche vectorielle nue : ni `IntentRouter`, ni `RetrievalPlan`, ni filtre de
nœud, ni suppression des sections `history`. Il sert a controler corpus et embeddings, pas a juger
la securite du coach.

## Eval V2 (Production-Shaped)

Eval V2 est le juge du coach. Le runner execute le vrai pipeline (`IntentRouter` ->
`build_retrieval_plan` -> `RagService`), verifie le snapshot gele et son lien avec le jeu d'eval,
ouvre la collection en lecture seule avec la provenance du snapshot, puis note chaque cas.

Ingresser le corpus complet dans une nouvelle collection, puis valider et evaluer (le nom de
collection est donne par la sortie de l'ingestion) :

```bash
uv run python -m backend.app.ingestion.cli \
  --snapshot-dir .scratch/rag/corpus/wikibooks-snapshot \
  --ingest-mode full

uv run python -m backend.app.ingestion.cli \
  --snapshot-dir .scratch/rag/corpus/wikibooks-snapshot \
  --no-ingest \
  --collection NOM_DE_LA_COLLECTION

uv run python -m experiments.rag.eval_v2.retrieve --collection NOM_DE_LA_COLLECTION
```

Artifacts sous `experiments/rag/eval_v2/runs/<horodatage>/` : `run.json` (collection, digest,
snapshot), `pipeline.json` (contexte de l'arbre, decision d'intention, plan, resultats RAG),
`retrieved.json`, `report.json`.

Ce qu'il faut lire dans `report.json` :

- `coach_usable_context_rate` : gate du coach.
- `deep_descendant_pollution_rate`, `history_pollution_rate`, `misc_pollution_rate` : pollution
  interdite, attendu a `0.0`.
- `false_current_line_rate` : prose d'une autre ligne presentee comme la ligne courante.
- `current_context_hit_rate` : la prose courante attendue est-elle retrievee.
- `secondary` : metriques de ranking, utiles pour comparer, insuffisantes seules.

Le runner echoue explicitement (code 2) si un cas rencontre `rag_store_unavailable` ou si aucun cas
ne retrieve de document : une collection incompatibile ou une provenance erronee ne produit donc
plus un rapport propre mais vide. La provenance est stricte : une collection sans `corpus` au
manifeste, ou construite sur un autre snapshot, est refusee.

## Reindexation Et Publication

Un recalcul complet des embeddings est requis si changent le schema vectoriel, le modele ou son
digest, la dimension, la metrique ou le format vectoriel. Un changement de cleaner, chunking,
granularite, texte ou metadonnees cree un nouveau snapshot; les vecteurs dont les IDs restent
compatibles peuvent etre reutilises, avec reecriture des metadonnees courantes. `k`, `search_ef` et
le seuil de score sont des parametres de retrieval et ne rendent pas les vecteurs incompatibles.

Publier seulement une collection dont les IDs finaux correspondent exactement au snapshot et dont
le run de reference a un digest resolu. Conserver son nom immutable. Le branchement applicatif ou un
futur alias stable peut alors pointer vers ce nom; un rollback repointe explicitement vers le
predecesseur valide. Aucune suppression ou rotation automatique n'est implementee.

## Securite Des Donnees

- Ne jamais supprimer le predecesseur avant validation de la nouvelle collection.
- Ne jamais utiliser `docker compose down -v` comme nettoyage : cette commande supprime les volumes
  Ollama, MongoDB et Milvus.
- `--allow-remote` est obligatoire pour autoriser explicitement un Milvus non loopback. Verifier la
  cible avant toute ecriture.
- Les collections CPU historiques de 52 chunks restent intactes; ne pas les presenter comme un
  baseline GPU.
- Wikibooks Chess Opening Theory est sous CC BY-SA : conserver l'URL, la licence et l'attribution,
  et respecter le partage a l'identique lors de toute redistribution.
