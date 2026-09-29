# Librairie d'echiquier Angular

Status: accepted

Le frontend Angular utilise `@lichess-org/chessground` pour le rendu et les interactions de l'echiquier, avec `chess.js` pour la logique d'echecs cote client : validation des coups, FEN, PGN et historique des coups.

`@lichess-org/chessground` est retenu parce que c'est la librairie d'echiquier web maintenue par l'ecosysteme Lichess, avec une excellente qualite d'interaction, le support mobile, le drag and drop, les callbacks de coups, le rendu responsive et les capacites visuelles utiles pour la suite de la demo.

La licence de Chessground est GPL-3.0-or-later. Ce risque est accepte pour le POC local et demonstratif. Avant toute distribution proprietaire ou passage en production, cette decision devra etre reevaluee avec le client et, si necessaire, remplacee par une alternative permissive comme `cm-chessboard`.

## Alternatives considerees

- `ngx-chessboard` : nom mentionne dans les documents initiaux, mais package non disponible sous ce nom sur npm lors de la recherche.
- `material-chessboard` : nom mentionne dans les documents initiaux, mais package non disponible sous ce nom sur npm lors de la recherche.
- `ngx-chess-board` : package Angular MIT disponible, mais faible activite, faible adoption et documentation orientee Angular 13.
- `cm-chessboard` : option MIT solide et recente, rejetee pour ce POC parce que Chessground offre une meilleure qualite d'interaction et de maintenance, et que le risque GPL est accepte.

## Consequences

- Le code Angular encapsule Chessground dans un composant dedie pour limiter le couplage.
- `chess.js` reste la source de verite pour les regles et notations cote client ; Chessground ne doit pas porter la logique metier.
- Les appels API frontend utilisent des chemins relatifs (`/api/...`) pour rester compatibles avec le proxy de developpement puis Docker Compose.
