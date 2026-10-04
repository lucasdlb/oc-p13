# RAG Milvus et modele d'embeddings

Status: accepted (2026-10-01, phase R mesuree ; **revise 2026-10-02 apres nettoyage du corpus et baseline GPU** ; **revise 2026-10-03 pour OpeningTree + eval v2**)

Ce document capture les decisions structurantes de la phase RAG/Milvus. Il complete `docs/DATA.md` (source de verite des sources et du schema Milvus) sans le dupliquer. Le plan de travail est dans `TODO.md`, non autoritaire.

> Revision 2026-10-01 : la revue `docs/reviews/2026-10-01-rag-phase-r-0-1-code-review.md` et la note
> `docs/reviews/2026-10-01-chess-openings-in-rag.md` ont invalide la conclusion mesuree d'origine.
> Les mesures precedentes melangeaient des metadonnees `chess-openings` quasi dupliquees avec de la
> prose, et la pertinence etait jugee par identite d'ouverture, pas par passage. Les corrections et les
> mesures refaites sont ci-dessous.

La comparaison avec l'evaluation d'un depot de reference est documentee dans
`docs/reviews/2026-10-01-rag-evaluation-comparison.md`. La revision 2026-10-03
adopte la consequence principale : le corpus Wikibooks complet et l'evaluation v2
doivent etre construits autour d'un arbre structure d'ouvertures avant toute
indexation Milvus et avant le cablage final du retrieval applicatif.

## Role des sources (revele)

`lichess-org/chess-openings` est une **donnee structuree** (arbre d'ouvertures nommees : `eco`, `name`,
`pgn`), pas de la prose pedagogique. Elle est donc retiree du corpus vectoriel : elle alimente le
matching local / la jointure `eco_code`, l'arbre d'ouvertures et la future collection MongoDB
`openings`, pas Milvus. Milvus ne contient que de la **prose pedagogique** (Wikibooks Chess Opening
Theory pour l'instant). Cela leve la tension de `docs/DATA.md` (Milvus ne doit pas contenir la source
canonique du matching).

L'explorateur d'ouvertures (`OpeningTree`) est maintenant une decision de prerequis pour le corpus
Wikibooks complet : les TSV `chess-openings` sont ingeres d'abord dans un snapshot structure offline,
puis charges par une classe Python deterministe. Ce snapshot fournit l'identite stable des noeuds, les
relations parent/enfants, l'index de positions et les metadonnees de jointure utilisees pour nettoyer,
mapper et evaluer Wikibooks. MongoDB reste la cible runtime ulterieure pour `openings`, mais la phase de
nettoyage et de snapshot Wikibooks ne doit pas dependre d'une base MongoDB disponible.

## Mesures de la phase R (refaites sur corpus nettoye)

Harness `experiments/rag/` sur le golden set francais (15 requetes, dont 13 notees), corpus **prose
seul et nettoye** (13 pages Wikibooks curees), embeddings `qwen3-embedding:0.6b` via Ollama, Milvus
Lite, `k=5`, retrieval purement semantique, jugements **au passage**
(`experiments/rag/judgments.json`), latence mesuree avec warm-up et 3 passes
(`--warmup 2 --repeats 3`). Les runs de reference sont `20261002T075844Z_section` et
`20261002T080035Z_page`.

| Granularite | chunks | hit@5 | MRR | nDCG@5 | latence totale p50 / p95 |
| --- | --- | --- | --- | --- | --- |
| `page` | 13 | 0.923 | 0.923 | 0.923 | 70 ms / 179 ms |
| **`section`** | 52 | 1.000 | 0.756 | 0.552 | 64 ms / 139 ms |

Latence de retrieval controlee : l'embedding de requete domine (p50 ~51-73 ms), la recherche Milvus
est ~5-7 ms. Les deux runs ont ete mesures dans les memes conditions (ingest puis warm-up puis passes).

**Lecture prudente.** Le score `page` est **gonfle par la taille du corpus** : avec 13 documents et
`k=5`, le top-5 couvre 38 % de la collection, donc retrouver la bonne page est presque trivial.
Malgre cela, `page` manque la requete `dame-c4`. Le score `section` teste le comportement utile au
coach : retrouver **le passage** qui explique l'idee, parmi 52 chunks, et atteint hit@5 1.000.
`recall@k` reste dilue (une page notee contient plusieurs sections). La granularite par defaut reste
donc **`section`** ; `page` reste un axe de config, et le choix sera revalide sur un corpus prose plus
large (corpus complet ou pages supplementaires).

Le nettoyage est structurel via `mwparserfromhell`. Les templates de position, references, tables
HTML/wikitext et liens de navigation sont retires ; les sections `Theory table`, `References`,
`See also`, `External links` et `Further reading` sont exclues avec leurs sous-sections. Les titres
pedagogiques, paragraphes, listes et libelles de liens sont conserves. L'adaptateur rejette une page
sans prose ou avec des marqueurs MediaWiki residuels. La version du nettoyeur participe a l'identite
de collection et a la provenance du run, afin qu'une collection sale ne puisse pas etre reutilisee.

- "ouverture espagnole" retrouve desormais la page Ruy Lopez (le corpus prose ne contient plus des
  milliers de lignes `chess-openings` concurrentes), mais les alias francais des noms propres restent
  un item ouvert (query expansion ou alias).
- Requetes hors corpus (ex. "attaque autrichienne", absente des 13 pages) et scenario hors theorie :
  **rapportes separement**, exclus des moyennes.

### Baseline GPU homogene des 52 chunks

Le run `20261002T093355241452Z_section` a reencode les 52 chunks sur la RTX 2060 dans la nouvelle
collection immutable schema 3 `chess_knowledge_rag_section_b5b673751585`. Le rapport d'ingestion
indique 52 demandes, 52 embeddings, zero reutilisation et une cardinalite finale de 52. Le runtime
declare `processor=gpu`, le scope `document_and_query_embeddings`, 2 370 652 077 octets de VRAM et
Ollama 0.35.0 ; `ollama ps` a confirme `100% GPU` apres le run. Le digest est reste
`ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d`.

| Mesure | CPU historique | GPU homogene |
| --- | ---: | ---: |
| Precision@1 / @3 / @5 | 0.615 / 0.462 / 0.308 | 0.615 / 0.462 / 0.308 |
| Hit@5 | 1.000 | 1.000 |
| Recall@5 | 0.536 | 0.536 |
| MRR | 0.756 | 0.756 |
| nDCG@5 | 0.552 | 0.553 |
| embedding p50 / p95 | 53.4 / 132.4 ms | 37.3 / 47.6 ms |
| recherche p50 / p95 | 6.9 / 10.3 ms | 6.3 / 9.9 ms |
| total p50 / p95 | 63.6 / 138.8 ms | 45.0 / 54.6 ms |
| ingestion / debit | non enregistre | 35.386 s embedding (1.469 chunks/s), 35.497 s total |
| cardinalite | 52 | 52 |

Le modele et son digest immuable, et non le processeur, sont l'identite principale des embeddings.
Quatre top-5 changent legerement d'ordre ou de cinquieme candidat entre les runs. Seule la requete
`gambit-roi` change une metrique de qualite : nDCG passe de 0.3462 a 0.3633 ; les autres metriques
agregees hors nDCG restent identiques.

Les jugements du benchmark v1 sont binaires et partiels. Precision@k est le nombre de passages juges
pertinents dans le top-k divise par k ; avec une seule section jugee pertinente, meme une recherche
parfaite plafonne donc a 0.2 pour Precision@5. Precision@5 reste une metrique diagnostique et ne doit
pas etre presentee comme la metrique principale ; nDCG est plus representative du classement ici.

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
- **Retrieval** : `k=5`, metrique COSINE, index HNSW (`M=16`, `efConstruction=200`, `ef=128`), dimension
  1024. Filtre `eco_code` doux cote production (non applique dans la mesure phase R).
- **Evaluation au passage.** La pertinence est jugee sur le passage source (page notee, et section notee
  en granularite `section`), pas sur l'identite d'ouverture. Les requetes hors corpus et hors theorie
  sont rapportees a part et exclues des moyennes.
- **Coach LLM** : Ollama `qwen2.5:7b-instruct` par defaut, challenger `qwen2.5:3b-instruct`, choisi en
  phase 4. Provider cloud : ADR separe.
- **Coach contraint** : generation structuree sourcee, chaque affirmation taggee par l'id de sa source,
  validee cote backend, chaine grounded -> prompt-only -> template deterministe.
- **LangGraph est reporte.** DAG deterministe dont chaque noeud appelle son outil par defaut, puis
  conditions documentees, a terme routage agentique. `RagService`/`CoachService` ne doivent pas importer
  `langgraph`.

## Consequences

- `docs/DATA.md` : `eco_code` reste la cle de jointure ; le role de `chess-openings` est corrige
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
- `config.toml` gagne `[embeddings]`, `[milvus]`, `[rag]`, `[llm]`. `MILVUS_URI` et `OLLAMA_BASE_URL`
  vivent dans `.env` ; tout `milvus.uri` / `embeddings.base_url` / `llm.base_url` en `config.toml` est
  ignore.
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
