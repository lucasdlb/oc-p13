# UX et interface Angular

Ce document est la source de verite pour l'experience utilisateur, les composants frontend et le layout de demonstration actuellement implementes.

## Objectif UX

L'interface doit permettre a un jeune joueur de jouer une ligne d'ouverture, de comprendre ce que la position signifie et de voir clairement les donnees qui soutiennent l'explication.

## Composition actuelle

```text
AppComponent
+-- LevelSelectorComponent
+-- ChessboardComponent
+-- MoveHistoryComponent
+-- AnalysisPanelComponent
    +-- CoachMarkdownComponent
    +-- Ouverture, explication, question et contexte pedagogique
    +-- Bouton d'analyse de position sans question
    +-- Videos et fallbacks
    +-- Explorer Lichess/Masters, coups, statistiques et Stockfish
```

Les blocs ouverture, coups recommandes, statistiques, Stockfish et videos ne sont pas des composants Angular autonomes : ils sont actuellement integres dans `AnalysisPanelComponent`.

## Flux utilisateur

1. L'utilisateur choisit un niveau : `debutant`, `intermediaire`, ou `avance`.
2. L'utilisateur joue un coup legal sur l'echiquier, ou demande un coup ou une ligne depuis le coach ou l'Explorer.
3. Le frontend met a jour la position FEN, le PGN, l'historique et les coups legaux. Le champ `moves` de la requete utilise les coups LAN produits par `chess.js`.
4. Le frontend appelle `POST /api/analyze-position`.
5. L'interface affiche un etat de chargement lisible, puis complete progressivement l'analyse avec les ressources YouTube, le contexte RAG, Stockfish et le flux du coach lorsque ces briques sont demandees. Le bouton « Analyser la position » lance une explication generale sans question precise ; le champ de question reste disponible pour une demande ciblee.
6. L'analyse affiche l'ECO et le nom de l'ouverture, l'explication, les coups recommandes, les statistiques Lichess, les coups et statistiques Masters lorsqu'ils sont disponibles, Stockfish et le contexte pedagogique source.
7. Les videos retournees par l'Explorer sont affichees avec leur miniature, chaine et duree lorsqu'elles sont disponibles. Un lien de recherche YouTube est affiche en fallback si la cle, le quota ou le service ne sont pas disponibles.
8. Le niveau pedagogique initialise une plage de niveau Lichess ; l'utilisateur peut ajuster les bornes min/max pour filtrer les statistiques pratiques. Toute modification relance l'analyse de la position courante.

## Layout desktop

```text
+----------------------------------------------------------------+
| En-tete : identite, niveau pedagogique, Demo 1. e4, reset      |
+----------------------------+-----------------------------------+
| Echiquier                  | Coach IA, ouverture, explication |
| Historique                 | Question, contexte, videos      |
|                            | Explorer, coups et statistiques |
|                            | Stockfish                       |
+----------------------------+-----------------------------------+
```

Le panneau d'analyse de droite empile le bloc Coach IA puis le bloc Explorer.

## Layout mobile

```text
En-tete : niveau pedagogique et actions
Echiquier
Historique
Coach IA : ouverture, explication, question et contexte
Videos et fallbacks s'ils existent
Explorer : coups recommandes et statistiques
Stockfish
```

Sous le breakpoint responsive actuel, le panneau d'analyse passe sous la colonne echiquier/historique. Le niveau reste dans l'en-tete, avant la zone de travail.

## Librairie echiquier

Decision : le frontend Angular utilise `@lichess-org/chessground` pour le rendu et les interactions de l'echiquier, avec `chess.js` pour la validation des coups, la production de FEN, PGN et coups LAN. Les coups recommandes de l'API sont fournis en UCI.

Cette decision est documentee dans `docs/adr/0004-angular-chessboard-library.md`. Chessground est GPL-3.0-or-later ; ce risque est accepte pour le POC local et devra etre reevalue avant une distribution proprietaire ou une mise en production.

Separation attendue :

- Chessground gere le rendu, le drag and drop, les callbacks d'interaction et l'etat visuel.
- `chess.js` gere les regles d'echecs, la legalite des coups, FEN, PGN et historique LAN.
- Angular reste non negociable et encapsule la librairie dans un composant dedie.

Les coups recommandes recus par l'API en UCI sont convertis en mouvements de plateau avant d'etre jouables dans l'interface.

## Lisibilite des sources

L'UI doit eviter de presenter une explication IA comme magique. Lorsque possible, afficher ou rendre accessible :

- ouverture identifiee ;
- ECO et nom de l'ouverture dans le bandeau d'analyse ;
- sources pedagogiques, URL et conditions de licence dans le contexte RAG lorsqu'elles sont disponibles ;
- statistiques Lichess ;
- coups Masters dans une section separee lorsque disponibles ;
- badges compacts sur les coups lorsqu'ils sont fournis, avec la source active et l'Elo moyen presentes separement ;
- etat de Stockfish, avec chargement, evaluation disponible, indisponibilite ou absence d'appel theorique ;
- videos lorsqu'elles sont disponibles ;
- fallback utilise si une brique est degradee.

Le champ technique `opening.source` n'est pas affiche dans le bandeau d'ouverture actuel ; l'attribution visible passe par les cartes de contexte pedagogique. Lorsqu'aucune video n'est retournee, l'interface n'affiche pas de message YouTube dedie mais peut afficher les fallbacks retournes par le backend.

## References coach

La prose du coach utilise le langage code de l'ADR 0008 pour distinguer les
intentions echiqueennes :

- un `move` legal est survolable et jouable ;
- un `square` est surlignable mais ne joue jamais un coup ;
- une `line` legale est survolable comme variante et jouable en une action ;
- une reference illegale, notamment pour l'autre couleur, reste du texte
  desactive.

Les SAN nus ne sont jamais convertis automatiquement en controles interactifs.
