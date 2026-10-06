# RAG Milvus et modele d'embeddings

Status: accepted (2026-10-01, phase R mesuree ; **revise 2026-10-02 apres nettoyage du corpus et baseline GPU** ; **revise 2026-10-03 pour OpeningTree + eval v2**)

Ce document capture les decisions structurantes de la phase RAG/Milvus. Il complete `docs/data/milvus.md` et `docs/data/sources.md` sans dupliquer leurs contrats.

> Revision 2026-10-01 : les constats de revue de la phase R ont invalide la conclusion mesuree
> d'origine et sont integres dans les decisions ci-dessous.
> Les mesures precedentes melangeaient des metadonnees `chess-openings` quasi dupliquees avec de la
> prose, et la pertinence etait jugee par identite d'ouverture, pas par passage. Les corrections et les
> mesures refaites sont ci-dessous.

La comparaison avec l'evaluation d'un depot de reference a conduit a la revision 2026-10-03 :
le corpus Wikibooks complet et l'evaluation v2
doivent etre construits autour d'un arbre structure d'ouvertures avant toute
indexation Milvus et avant le cablage final du retrieval applicatif.

## Role des sources (revele)

`lichess-org/chess-openings` est une **donnee structuree** (arbre d'ouvertures nommees : `eco`, `name`,
`pgn`), pas de la prose pedagogique. Elle est donc retiree du corpus vectoriel : elle alimente le
matching local / la jointure `eco_code`, l'arbre d'ouvertures et la future collection MongoDB
`openings`, pas Milvus. Milvus ne contient que de la **prose pedagogique** (Wikibooks Chess Opening
Theory pour l'instant). Cela leve la tension de `docs/data/milvus.md` (Milvus ne doit pas contenir la source
canonique du matching).

L'explorateur d'ouvertures (`OpeningTree`) est maintenant une decision de prerequis pour le corpus
Wikibooks complet : les TSV `chess-openings` sont ingeres d'abord dans un snapshot structure offline,
puis charges par une classe Python deterministe. Ce snapshot fournit l'identite stable des noeuds, les
relations parent/enfants, l'index de positions et les metadonnees de jointure utilisees pour nettoyer,
mapper et evaluer Wikibooks. MongoDB reste la cible runtime ulterieure pour `openings`, mais la phase de
nettoyage et de snapshot Wikibooks ne doit pas dependre d'une base MongoDB disponible.

## Evaluation

Les mesures et les runs de reference sont conserves dans `docs/RAG-EVALUATION.md`. Cette separation
evite de melanger les decisions structurelles avec les resultats experimentaux, qui seront enrichis
au fil des corpus et des definitions de metriques.

## Contexte

Milvus est une brique non negociable (ADR 0002). Avant cette phase, `rag_context` et
`coach_explanation` etaient des placeholders templates (`backend/app/services/analysis.py:132` et
`:436`). Cette phase prepare un RAG reel de bout en bout.

Le cahier des charges (`docs/PROJECT.md`) ne nomme pas de modele d'embeddings : le choix est une
decision projet, validee par mesure en phase R.

## Decisions

- **Une seule collection, un seul pipeline de retrieval.** La collection `chess_knowledge` porte un
  modele d'embeddings, une dimension et une metrique. Les sources de prose se distinguent par metadata
  (`source`, `opening_name`, `eco_code`, `page_id`), pas par store. Chaque source a son **adaptateur
  d'ingestion**, pas son propre retrieval.
- **`chess-openings` n'est pas indexe dans Milvus.** C'est une source structuree (CC0-1.0) : matching /
  jointure `eco_code` / alias / arbre d'ouverture, via un snapshot `OpeningTree` offline puis une classe
  Python deterministe. MongoDB `openings` sera seedee plus tard depuis le meme snapshot pour le runtime,
  mais le nettoyage Wikibooks et l'evaluation ne dependent pas de MongoDB. Wikibooks Chess Opening Theory
  est la source de prose pedagogique (CC BY-SA, anglais). Lichess studies est reportee en v2.
- **`OpeningTree` est le prerequis metadata du corpus Wikibooks.** Le pipeline consomme les TSV
  `chess-openings`, derive les coups UCI, FEN/EPD, parents, enfants, profondeurs et eventuelles
  transpositions avec `python-chess`, puis ecrit un snapshot JSON versionne. Les pages et chunks
  Wikibooks sont ensuite enrichis depuis cet arbre (`opening_node_id`, `opening_path`, `eco_code`,
  `opening_name`, `line_pgn`, `move_sequence`) avant validation et ingestion Milvus.
- **`OpeningTree` pilote les filtres metadata du retrieval vectoriel.** Il ne remplace pas la recherche
  vectorielle : il identifie le noeud courant et la fenetre locale, puis produit les contraintes metadata
  et relationnelles appliquees aux chunks vectorises (`opening_node_id`, `eco_code`, relation au noeud
  courant, enfants directs autorises, descendants profonds exclus ou penalises). Milvus reste le moteur de
  similarite sur la prose ; l'arbre borne le rayon de recherche et fournit les penalites de distance.
- **Eval v2 production-shaped avant retrieval final.** Le benchmark phase R reste une baseline technique.
  La prochaine evaluation doit juger si le contexte aide le coach sans le faire mentir : hit du contexte
  courant, contexte enfant autorise, pollution par descendants profonds, pollution history/misc, fausse
  ligne courante, attribution de source et utilisabilite coach. `OpeningTreeContext`, `IntentRouter`,
  `RagService` et `CoachService` restent derriere ce corpus et cette evaluation.
- **Modele d'embeddings par defaut : Qwen3-Embedding-0.6B** (0.6B, jusqu'a 1024 dim avec MRL 32-1024,
  contexte 32K, 100+ langues, instruction-aware, Apache-2.0). Challenger : `BAAI/bge-m3`. Repli si trop
  lourd : `intfloat/multilingual-e5-base`. Le provider est isole derriere `EmbeddingProvider`.
- **Strategie linguistique : option A par defaut.** Corpus en anglais, requetes en francais, embedding
  multilingue, synthese francaise. Les options B (traduction a l'ingestion) et C (corpus FR natif)
  restent ouvertes.
- **Chunking par budget d'octets UTF-8, sans recouvrement.** Le plafond est un budget d'octets (les
  limites `VARCHAR` de Milvus sont en octets), pas un nombre de "tokens" compte en mots. Une section
  trop longue est **decoupee en plusieurs chunks ordonnes** (`part_index`) sans perte de contenu ; une
  **page** trop longue est **rejetee** (`ChunkerError`), pas silencieusement tronquee. La prose est par
  defaut en `section`, avec reconstruction possible via `page_id`.
- **Identite de page et reconstruction.** Chaque chunk porte `page_id = <source>::<page_title>`,
  `section_index` et `part_index`, ce qui permet de reassembler la page a partir des sections
  retrouvees (`chunker.reconstruct_page`).
- **Milvus Lite pour le dev/tests**, Milvus Standalone (etcd + minio + milvus) dans `docker-compose.yml`
  pour la demo. Le meme client `pymilvus` sert les deux via `MILVUS_URI`.
- **Compatibilite de collection obligatoire.** Chaque collection porte un **manifeste** (version de
  schema, dimension, metrique, index, signature d'embeddings). Reutiliser une collection existante
  exige un manifeste identique ; sinon reindexation (`MilvusStoreError`). Les limites `VARCHAR` sont
  validees en octets UTF-8 au moment de l'upsert.
- **Reindexation non destructive.** Les collections du harness sont **versionnees par empreinte**
  (schema + modele + dimension + granularite + hash corpus). On ne supprime jamais l'ancienne avant que
  la nouvelle soit ingeree et validee (cardinalite verifiee). Un hote Milvus non-loopback exige
  `--allow-remote`.
- **Provenance complete.** Chaque run enregistre la config effective validee, le **digest** immuable du
  modele Ollama, les hashes corpus / golden set / jugements, le sha git + etat dirty, le mode
  ingest/no-ingest, la cardinalite demandee vs stockee et les hits retrouves.
- **Fallback documente.** Si Milvus est indisponible, l'analyse renvoie un `rag_context` vide explicite
  et ajoute une entree dans `fallbacks_used`; elle n'echoue jamais. Le cablage reste a faire en phase 3.
- **Retrieval** : `k=5`, metrique COSINE, index HNSW (`M=16`, `efConstruction=200`, `ef=64`), dimension
  1024. Filtre `eco_code` doux cote production (non applique dans la mesure phase R).
- **Evaluation au passage.** La pertinence est jugee sur le passage source (page notee, et section notee
  en granularite `section`), pas sur l'identite d'ouverture. Les requetes hors corpus et hors theorie
  sont rapportees a part et exclues des moyennes.
- **Coach LLM** : le provider, le modele et l'URL sont choisis dans `config.toml`. NVIDIA NIM est le
  provider par defaut actuel ; Ollama et Mistral utilisent le meme seam `LLMProvider`. Les secrets
  sont valides par Pydantic selon le provider choisi.
- **Coach contraint** : generation structuree sourcee, chaque affirmation taggee par l'id de sa source,
  validee cote backend, chaine grounded -> prompt-only -> template deterministe.
- **LangGraph est orchestre par ADR 0009.** Le graphe reste un module mince d'orchestration : DAG
  deterministe, conditions documentees, puis agentivite bornee. `RagService`/`CoachService` ne doivent
  pas importer `langgraph`. Le chemin imperatif reste la reference testable et desactivable.

## Consequences

- `docs/data/milvus.md` : `eco_code` reste la cle de jointure ; le role de `chess-openings` est corrige
  (structure, hors Milvus) ; le schema `chess_knowledge` gagne `page_id`, `section_index`, `part_index`.
  La prochaine revision de schema doit ajouter les metadonnees derivees de `OpeningTree` necessaires au
  corpus Wikibooks complet (`canonical_title`, `wikibooks_revision_id`, `opening_node_id`,
  `opening_path`, `line_pgn` / `move_sequence`, `intent`, `side`, `tags`, `is_history`, `is_misc`).
- Le pipeline corpus devient : `chess-openings` TSV -> snapshot `OpeningTree` -> discovery/fetch
  Wikibooks -> manifest versionne -> nettoyage/rapport qualite -> mapping vers `OpeningTree` -> snapshot
  valide -> ingestion Milvus. L'ordre inverse (`fetch all` puis vectorisation immediate) est refuse.
- La migration MongoDB `openings` reste utile pour le runtime, mais elle consomme le snapshot structure ;
  elle n'est pas un prerequis pour construire le corpus Wikibooks propre.
- Le retrieval applicatif doit obtenir ses filtres depuis `OpeningTree` plutot que reconstruire une logique
  parallele depuis les chunks Milvus. Exemple : prose du noeud courant prioritaire, prose des enfants
  directs seulement comme suites conditionnelles, descendants plus profonds exclus par defaut, et sections
  `history` / `misc` exclues ou penalisees sauf intention explicite.
- `config.toml` porte les choix non secrets `[embeddings]`, `[milvus]`, `[rag]` et `[llm]`, y compris
  le provider, le modele et les URLs des providers LLM. `MILVUS_URI` et `OLLAMA_BASE_URL` restent
  des valeurs d'environnement pour les connexions machine-specific ; les secrets LLM sont
  provider-specific (`NVIDIA_API_KEY`, `MISTRAL_API_KEY`) et valides par Pydantic.
- `minio/minio` a retire ses images Docker Hub ; la compose utilise `bitnamilegacy/minio`. Les
  credentials `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` sont propages a Milvus
  (`MINIO_ACCESS_KEY_ID` / `MINIO_SECRET_ACCESS_KEY`) pour que MinIO reste joignable en cas de
  surcharge.
- Les licences restent a surveiller : Wikibooks est CC BY-SA (attribution + partage a l'identique),
  a revalider avant distribution hors POC.
- Le harness `experiments/rag/` reste versionne, les corpus/bases dans `.scratch/rag/` (gitignore).
- Les anciens runs `experiments/rag/runs/20261001T1756*` sont **historiques et invalides** pour toute
  conclusion architecturale (corpus contamine par les metadonnees, pertinence par identite, latence non
  controlee). Les runs `20261001T204044Z_section` et `20261001T204234Z_page` sont egalement remplaces :
  ils contenaient des tables de theorie aplaties et des sections de navigation.
