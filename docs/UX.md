# UX et interface Angular

Ce document est la source de verite pour l'experience utilisateur, les composants frontend et le layout de demonstration.

## Objectif UX

L'interface doit permettre a un jeune joueur de jouer une ligne d'ouverture, de comprendre ce que la position signifie et de voir clairement les donnees qui soutiennent l'explication.

## Composants cibles

```text
AppComponent
+-- ChessboardComponent
+-- LevelSelectorComponent
+-- MoveHistoryComponent
+-- AnalysisPanelComponent
+-- RecommendedMovesComponent
+-- OpeningInfoComponent
+-- LichessStatsComponent
+-- StockfishPanelComponent
+-- VideosPanelComponent
```

## Flux utilisateur

1. L'utilisateur choisit un niveau : `debutant`, `intermediaire`, ou `avance`.
2. L'utilisateur joue un coup sur l'echiquier.
3. Le frontend met a jour FEN, PGN et coups UCI.
4. Le frontend appelle `POST /api/analyze-position`.
5. L'interface affiche un etat de chargement lisible.
6. L'analyse apparait avec ouverture, coups, explication, stats, Stockfish si utile, Masters si disponible, et videos ou fallback.
7. Le niveau pedagogique initialise une plage de niveau Lichess ; l'utilisateur peut ajuster les bornes min/max pour filtrer les statistiques pratiques.

## Layout desktop

```text
+--------------------------------------------------+
| Echiquier + historique | Analyse coach           |
|                        | Coups recommandes       |
|                        | Stats Lichess           |
|                        | Stockfish               |
|                        | Videos                  |
+--------------------------------------------------+
```

## Layout mobile

```text
Echiquier
Niveau pedagogique
Coup recommande
Explication
Stats
Stockfish si present
Videos ou fallback
Historique
```

## Librairie echiquier

Decision : le frontend Angular utilise `@lichess-org/chessground` pour le rendu et les interactions de l'echiquier, avec `chess.js` pour la validation des coups, la production de FEN, PGN et coups UCI/LAN.

Cette decision est documentee dans `docs/adr/0004-angular-chessboard-library.md`. Chessground est GPL-3.0-or-later ; ce risque est accepte pour le POC local et devra etre reevalue avant une distribution proprietaire ou une mise en production.

Separation attendue :

- Chessground gere le rendu, le drag and drop, les callbacks d'interaction et l'etat visuel.
- `chess.js` gere les regles d'echecs, la legalite des coups, FEN, PGN et historique.
- Angular reste non negociable et encapsule la librairie dans un composant dedie.

## Lisibilite des sources

L'UI doit eviter de presenter une explication IA comme magique. Lorsque possible, afficher ou rendre accessible :

- ouverture identifiee et source ;
- statistiques Lichess ;
- coups Masters dans une section separee lorsque disponibles ;
- badges compacts de source ou de faible echantillon sur les coups ;
- indication que Stockfish a ete appele ;
- videos ou fallback YouTube ;
- fallback utilise si une brique est degradee.
