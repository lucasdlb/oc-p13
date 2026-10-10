# Sources

Ce fichier est le registre court des sources et de leur role. Toute source centrale doit avoir une
licence ou des conditions d'utilisation verifiees avant d'etre utilisee dans la demo.

| Source | Role | Statut | Licence / condition |
| --- | --- | --- | --- |
| `demo-opening-seed` | fallback local pour les scenarios MVP | valide POC | donnees embarquees dans le depot |
| `lichess-org/chess-openings` | matching, arbre, jointure ECO | valide | CC0-1.0 |
| Lichess Opening Explorer | statistiques live, coups populaires, identite prioritaire | utilise | token OAuth, API distante, cache MongoDB, fallback seed |
| Lichess Cloud Evaluation | voie rapide optionnelle pour evaluations moteur pre-calculees | reporte | endpoint distant, couverture partielle, score point de vue Blancs |
| Wikibooks Chess Opening Theory | prose pedagogique RAG | a verifier | CC BY-SA, attribution et partage a l'identique |
| Wikichess / FICGS | source pedagogique optionnelle | a verifier | HTML et conditions a challenger |
| YouTube Data API | videos explicatives | utilise | cle API, quota, cache MongoDB, filtrage duree, fallback lien de recherche |
| Stockfish | evaluation moteur locale garantie hors theorie | valide POC | binaire local, score point de vue du trait, cache sur succes |

## Stockfish Et Cloud Eval

Stockfish et Cloud Eval produisent tous deux des faits moteur, mais leur fonctionnement differe.

- Stockfish calcule localement en direct depuis le FEN. Il fonctionne sur toute position legale si
  le binaire est disponible, avec un budget borne par `config.toml`.
- Cloud Eval interroge une base distante d'evaluations pre-calculees. C'est potentiellement plus
  profond et rapide sur hit, mais seulement pour les positions couvertes par Lichess.
- Stockfish renvoie le score du point de vue du trait; Cloud Eval renvoie le score du point de vue
  des Blancs. Toute integration doit normaliser la perspective avant affichage ou comparaison.

## Separation

- `chess-openings` est une donnee structuree et ne va pas dans Milvus.
- Wikibooks fournit la prose vectorisee et ne devient pas la source canonique du matching.
- Lichess Opening Explorer identifie prioritairement l'ouverture affichee quand sa reponse est
  valide et fournit les statistiques filtrees.
- Le coach distingue les faits externes, la prose pedagogique et ses formulations.

La politique complete de validation est dans
`docs/adr/0003-data-sources-and-source-validation-policy.md`.
