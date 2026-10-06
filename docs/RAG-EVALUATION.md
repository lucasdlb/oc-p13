# Evaluation RAG

Ce document conserve les metriques et les runs de reference du retrieval. Les decisions
structurelles restent dans `docs/adr/0006-rag-milvus-and-embeddings.md`; les commandes et la
procedure sont dans `docs/runbooks/RAG.md`.

## Baseline Phase R

Corpus prose Wikibooks nettoye, 13 pages, 52 sections, embeddings `qwen3-embedding:0.6b`,
Milvus Lite, `k=5`, retrieval semantique et jugements au passage.

| Granularite | Chunks | Hit@5 | MRR | nDCG@5 | Latence totale p50 / p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `page` | 13 | 0.923 | 0.923 | 0.923 | 70 ms / 179 ms |
| `section` | 52 | 1.000 | 0.756 | 0.552 | 64 ms / 139 ms |

La granularite par defaut est `section`. Le score `page` est peu discriminant avec un petit
corpus et `k=5`; les mesures doivent etre relancees quand le corpus pedagogique s'elargit.

## Baseline GPU

Run `20261002T093355241452Z_section`, collection schema 3 historique. Les vecteurs ont ete
recalcules sur GPU avec le meme modele et le meme digest.

| Mesure | CPU historique | GPU homogene |
| --- | ---: | ---: |
| Hit@5 | 1.000 | 1.000 |
| Recall@5 | 0.536 | 0.536 |
| MRR | 0.756 | 0.756 |
| nDCG@5 | 0.552 | 0.553 |
| Embedding p50 / p95 | 53.4 / 132.4 ms | 37.3 / 47.6 ms |
| Recherche p50 / p95 | 6.9 / 10.3 ms | 6.3 / 9.9 ms |
| Total p50 / p95 | 63.6 / 138.8 ms | 45.0 / 54.6 ms |

Cette baseline est historique et ne doit pas être confondue avec le schema runtime actuel.

## Eval V2

Eval V2 mesure le contexte utile au coach, et pas seulement l'identite de l'ouverture. Les gates
doivent au minimum couvrir:

- `coach_usable_context_rate`;
- `false_current_line_rate`;
- `false_context_rate`;
- hit du contexte courant et des enfants directs;
- pollution par descendants profonds, historique et contenu divers;
- attribution et licence des sources;
- latence et taux de fallback.

Chaque nouveau run doit enregistrer la collection, le schema, le modele et son digest, le hash du
corpus, le hash du golden set, le commit git et les parametres de retrieval. Ne compare pas des
runs produits avec des definitions de metriques differentes sans documenter la rupture.

## Regle De Publication

Une metrique n'est une baseline acceptee que si le run est reproductible, la provenance est complete
et les requetes hors corpus sont rapportees separement. Les artefacts de runs volumineux restent dans
les repertoires d'experimentation ou `.scratch/`, pas dans ce document.
