# Opportunites Data

Ces idees ne sont pas des engagements. Une idee devient du travail seulement quand elle entre dans
`docs/PLAN.md` ou fait l'objet d'une ADR.

## Parties De Reference

- Voir le catalogue de [`lichess-opening-explorer.md`](lichess-opening-explorer.md) pour `topGames`,
  `recentGames`, `moves[].game` et `history[]`.
- afficher la partie representative d'un coup recommande;
- injecter une ou deux parties annotees dans le contexte RAG;
- comparer theorie Masters et pratique Lichess;
- montrer la recence des tendances.

## Visualisation

- afficher le nom d'ouverture atteint par chaque coup;
- afficher l'evolution temporelle via `history[]`;
- enrichir les cartes de parties avec joueurs, ratings et cadence;
- afficher les tailles exactes des echantillons.

## Coaching Et Moteur

- Voir le catalogue de [`stockfish.md`](stockfish.md) pour `pv`, `multipv`, `wdl`, `nodes` et
  `seldepth`.
- Voir [`lichess-cloud-eval.md`](lichess-cloud-eval.md) pour les PV profondes et `knodes`.
- PV courte, MultiPV et WDL;
- detection de perte d'evaluation avant/apres un coup;
- normalisation du score vers une perspective explicite;
- Cloud Eval comme voie rapide pour les positions couvertes.

Chaque affirmation tactique doit rester supportee par une preuve moteur compatible; une prose seule
ne suffit pas pour le mot « piege ».
