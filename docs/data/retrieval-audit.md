# Audit Du Retrieval

Ce fichier conserve les limites connues entre payloads externes, modeles internes, caches et coach.

| Capacite | Recuperee | Perte / impact |
| --- | --- | --- |
| Totaux Lichess | oui, en pourcentages | les comptes bruts ne sont pas conserves dans le modele |
| Identite ECO/nom | oui | complete |
| Coups populaires | oui | complete pour le MVP |
| Parties top/recentes | non | pas d'exemples de parties dans le coach |
| Historique mensuel | non | pas de tendance |
| PV/MultiPV Stockfish | non | pas de continuations moteur |
| WDL et comptage moteur | non | pas d'indicateur de confiance |
| Perspective du score | non normalisee | risque d'ambiguite cote UI |
| Cloud Eval | non | candidat non implemente |

## Notes De Correction

- Les payloads Lichess sont stricts: un compteur absent declenche le fallback seed, pas un zero.
- Le cache Lichess conserve le modele mappe; les futurs besoins de comptes exacts exigent un nouveau
  contrat de cache.
- La profondeur affichee par le backend est la profondeur demandee, pas necessairement la derniere
  profondeur `info` observee.
- Cloud Eval et Stockfish n'ont pas la meme convention de score.
- Les filtres non utilises des endpoints Lichess ne sont pas dans la cle de cache actuelle.
- Toute activation d'un nouveau filtre doit modifier la cle de cache correspondante.

Les nouveaux ecarts et resultats de benchmark vont dans
[`../RAG-EVALUATION.md`](../RAG-EVALUATION.md) ou dans un test, pas dans ce catalogue.
