# Evaluation RAG

Ce document resume l'etat de livraison du retrieval RAG. Les decisions structurelles restent dans
`docs/adr/0006-rag-milvus-and-embeddings.md`; les commandes reproductibles sont dans
`docs/runbooks/RAG.md`.

## Conclusion POC

Le RAG est suffisant pour une demonstration POC : il fournit un contexte pedagogique source, evite de
presenter une ligne enfant comme ligne courante et expose les fallbacks. Il reste limite par la
couverture du corpus et par la pollution de contexte non critique.

Le run de reference actuel est `experiments/rag/eval_v2/runs/20261004T150555741956Z/`.

| Metrique | Valeur | Lecture |
| --- | ---: | --- |
| Cas evalues | 20 | Jeu Eval V2 oriente coach |
| `coach_usable_context_rate` | 0.80 | 80 % des cas fournissent un contexte exploitable par le coach |
| `false_current_line_rate` | 0.00 | Aucun enfant/prolongement n'est presente comme ligne courante |
| `false_context_rate` | 0.447 | Limite connue : contexte parfois trop large ou peu utile |
| `current_context_hit_rate` | 0.60 | La position courante est retrouvee dans 60 % des cas evalues |
| `child_context_hit_rate` | 1.00 | Les enfants attendus sont retrouves quand la question les demande |
| `source_attribution_ok_rate` | 1.00 | Les sources et licences sont presentes dans les resultats evalues |
| Latence totale p50 / p95 | 68 ms / 275 ms | Mesure du run Eval V2, hors generation coach |

Decision : acceptable pour le POC, a condition de presenter le RAG comme une aide sourcee et non
comme une base exhaustive d'ouvertures.

## Points Forts

- Le retrieval utilise le pipeline runtime : `IntentRouter`, `RetrievalPlan`, `RagService` et Milvus.
- La provenance des sources est visible dans l'UI : titre, URL, licence ou conditions.
- Le taux `false_current_line_rate` nul valide la garde principale du coach : ne pas affirmer qu'une
  suite non jouee est la position actuelle.
- Les cas de question sur les suites directes retrouvent les enfants attendus dans le run de reference.

## Limites Connues

- `false_context_rate` reste eleve : certains passages retournes sont corrects mais trop generaux,
  parents, ou insuffisamment utiles pour la question.
- Le corpus Wikibooks ne couvre pas toutes les lignes jouables; une absence de source doit rester
  visible plutot que forcee.
- Les metriques Eval V2 jugent le contexte transmis au coach, pas la qualite finale de la prose LLM.
- Les mesures de latence dependent du cache, du runtime Milvus et de l'etat local des embeddings.

## Baselines Historiques

Corpus prose Wikibooks nettoye, 13 pages, 52 sections, embeddings `qwen3-embedding:0.6b`, Milvus
Lite, `k=5`, retrieval semantique et jugements au passage.

| Granularite | Chunks | Hit@5 | MRR | nDCG@5 | Latence totale p50 / p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `page` | 13 | 0.923 | 0.923 | 0.923 | 70 ms / 179 ms |
| `section` | 52 | 1.000 | 0.756 | 0.552 | 64 ms / 139 ms |

Run GPU historique `20261002T093355241452Z_section`, schema 3 : Hit@5 stable a 1.000, total p50
ameliore de 63.6 ms a 45.0 ms. Cette baseline ne doit pas etre confondue avec le schema runtime
actuel.

## Routing A/B

Le dernier comparatif est `experiments/rag/eval_v2/runs/ab/20261007T103247980226Z/analysis.md`.

| Bras | Accuracy intention | Accuracy adversarial | Fallback rate | Coach usable context |
| --- | ---: | ---: | ---: | ---: |
| Regles deterministes | 0.8125 | 0.750 | 0.000 | 0.1875 |
| JEV restricted | 0.8125 | 0.750 | 0.031 | 0.1875 |
| JEV full | 0.8125 | 0.750 | 0.063 | 0.1875 |

Decision : garder le routeur deterministe dans le pipeline de demonstration. JEV progresse sur un
jeu de routing isole, mais n'ameliore pas encore le contexte utile au coach dans le pipeline complet.

## Regle De Publication

Une metrique n'est une baseline acceptee que si le run enregistre la collection, le schema, le modele,
le digest, le hash du corpus, le hash du jeu d'evaluation, le commit git et les parametres de
retrieval. Les artefacts volumineux restent dans `experiments/rag/` ou `.scratch/`, pas dans ce
document.
