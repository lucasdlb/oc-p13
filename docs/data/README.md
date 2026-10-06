# Donnees

Cette branche documente les donnees du POC. Chaque fichier a une responsabilite courte et
correspond a une zone du code.

| Besoin | Document |
| --- | --- |
| Comprendre la separation des donnees | [`sources.md`](sources.md) |
| Comprendre les collections et caches MongoDB | [`mongodb.md`](mongodb.md) |
| Comprendre le corpus et le schema Milvus | [`milvus.md`](milvus.md) |
| Integrer ou verifier Lichess Explorer | [`lichess-opening-explorer.md`](lichess-opening-explorer.md) |
| Evaluer l'option Lichess Cloud Eval | [`lichess-cloud-eval.md`](lichess-cloud-eval.md) |
| Integrer ou faire evoluer Stockfish | [`stockfish.md`](stockfish.md) |
| Voir les pertes et limites du mapping | [`retrieval-audit.md`](retrieval-audit.md) |
| Voir les opportunites non engagees | [`opportunities.md`](opportunities.md) |

## Autorite Par Donnee

| Donnee | Autorite | Fallback |
| --- | --- | --- |
| Identite d'ouverture | Lichess Opening Explorer | seed local / `OpeningTree` |
| Arbre d'ouvertures | snapshot `chess-openings` / `OpeningTree` | seed local |
| Prose pedagogique | Wikibooks dans Milvus | contexte RAG vide explicite |
| Historique de session | MongoDB `sessions` | analyse sans persistance |
| Etat d'un run progressif | MongoDB `analysis_runs` | aucun stockage durable |
| Statistiques externes | caches MongoDB | appel direct ou seed |
| Fait moteur | Stockfish | statut `unavailable` |

## Regles De Maintenance

- Un changement de modele Pydantic ou de persistance se reflete dans `mongodb.md` ou `milvus.md`.
- Un changement de contrat externe se reflete dans le fichier de la source concernee.
- Une nouvelle metrique va dans `docs/RAG-EVALUATION.md`, jamais dans un schema de donnees.
- Les decisions de trajectoire restent dans `docs/adr/`; les details d'execution restent dans les
  fichiers data ou les runbooks.
