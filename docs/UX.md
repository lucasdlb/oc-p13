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
6. L'analyse apparait avec ouverture, coups, explication, stats, Stockfish si utile, et videos ou fallback.

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

La librairie Angular d'echiquier reste une decision ouverte. Elle doit etre choisie apres recherche cadree comparant au minimum : compatibilite Angular, maintenance, capacite a produire FEN/PGN/UCI, effort d'integration et qualite demo.

Candidats initiaux :

- `ngx-chessboard`
- `material-chessboard`
- autre librairie Angular validee par recherche

Angular reste non negociable. Une librairie peut changer, pas le framework frontend.

## Lisibilite des sources

L'UI doit eviter de presenter une explication IA comme magique. Lorsque possible, afficher ou rendre accessible :

- ouverture identifiee et source ;
- statistiques Lichess ;
- indication que Stockfish a ete appele ;
- videos ou fallback YouTube ;
- fallback utilise si une brique est degradee.
