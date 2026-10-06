# Langage de references interactives du coach

Status: accepted (2026-10-05)

## Contexte

Le texte naturel du coach peut contenir un nom de coup, une case strategique,
un coup de la couleur adverse ou une suite de coups. Reconnaitre un SAN brut
dans la prose ne permet pas de distinguer ces intentions et peut produire un
bouton illegal ou une fleche pour le mauvais trait.

## Decision

Le coach utilise trois marqueurs inline explicites :

```text
[[move:uci=e7e5,label=e5]]
[[square:sq=e5,label=e5]]
[[line:moves=e2e4,e7e5,g1f3,label=e4 puis ...e5 puis Nf3]]
```

La grammaire est volontairement reduite :

- `move` represente un seul coup en UCI ; `label` est le texte visible.
- `square` represente une case et n'est jamais interprete comme un coup.
- `line` represente une sequence UCI valide ; `label` est le texte visible.
- Les valeurs `label` ne contiennent pas de virgule ni `]]`.
- Un coup interactif doit appartenir aux coups fournis par l'Explorer, Stockfish
  ou une continuation directe de l'arbre d'ouverture.

Le backend parse et assainit les marqueurs avant de persister le resultat. Un
coup doit aussi etre legal depuis la FEN courante ; une ligne est validee coup
par coup en alternant les couleurs. Un marqueur invalide est remplace par son
label lisible, sans interaction.

## Comportement UI

- `move` legal : survol d'une fleche et clic pour jouer le coup.
- `move` illegal ou d'une autre couleur : texte desactive, sans clic.
- `square` : survol et clic de surlignage de la case, sans jouer de coup.
- `line` legale : survol du premier coup et clic pour jouer toute la ligne de
  maniere atomique ; une ligne illegale est desactivee.

Le frontend ne transforme plus automatiquement les mots SAN nus. Le contrat
DSL est donc la seule source d'interaction dans la prose du coach.

## Consequences

- La sortie LLM reste du Markdown streamable, mais les references sont
  deterministes et testables.
- La validation depend de la FEN courante et des faits autorises du contexte.
- Les anciennes phrases contenant seulement `e5` restent de la prose et ne
  deviennent plus accidentellement des boutons.
