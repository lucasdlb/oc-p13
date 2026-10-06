# Lichess Opening Explorer

L'Explorer fournit l'identite d'ouverture, les statistiques et les coups populaires. Le backend
utilise `play`, `ratings` et `moves`; les autres filtres restent disponibles mais ne sont pas
envoyes par le POC.

## Endpoints

| Endpoint | Usage actuel | Parametres associes |
| --- | --- | --- |
| `/lichess` | statistiques et recommandations par niveau | `variant`, `fen`, `play`, `speeds`, `ratings`, `since`, `until`, `moves`, `topGames`, `recentGames`, `history` |
| `/masters` | theorie separee dans `masters_moves` | `fen`, `play`, `since`, `until`, `moves`, `topGames` |
| `/player` | non utilise; donnees personnelles hors MVP | `variant`, `fen`, `play`, `player`, `color`, `speeds`, `ratings`, `modes`, `since`, `until`, `moves`, `recentGames` |
| `/masters/pgn/{gameId}` | non utilise; candidat pour parties de reference | `gameId` |

Le POC utilise aujourd'hui seulement:

- `/lichess`: `variant=standard`, `play`, `ratings`, `moves`;
- `/masters`: `play`, `moves`.

Les autres parametres changent le perimetre des statistiques ou les objets additionnels inclus, pas
le schema general de la reponse. Par exemple, `speeds=blitz` retourne toujours `opening`,
`white/draws/black` et `moves[]`, mais calcule ces valeurs uniquement sur les parties blitz.

Tout nouveau parametre active doit entrer dans la cle de cache correspondante.

## Donnees Recuperees

- `opening.eco`, `opening.name`;
- compteurs `white`, `draws`, `black`;
- `moves[].uci`, `san`, `averageRating`, `white`, `draws`, `black`;
- pour Masters, les memes faits avec la source `masters-opening-explorer`.

Les parties, l'historique mensuel et les noms d'ouverture par coup sont actuellement ignores.
Les compteurs sont transformes en parts; le cache stocke le modele mappe et non le payload brut.

## Catalogue Des Champs

### `/lichess` et `/masters`

| Champ | Description | Recupere ? | Usage actuel / idee |
| --- | --- | --- | --- |
| `opening.eco` | Code ECO de la position nommee | oui | Identite et jointure de contexte |
| `opening.name` | Nom de l'ouverture | oui | Affichage et retrieval |
| `white` | Parties gagnees par les Blancs | oui | Transforme en pourcentage |
| `draws` | Parties nulles | oui | Transforme en pourcentage |
| `black` | Parties gagnees par les Noirs | oui | Transforme en pourcentage |
| `moves[].uci` | Coup candidat en notation UCI | oui | Recommandations et validation |
| `moves[].san` | Coup candidat lisible | oui | Affichage utilisateur |
| `moves[].averageRating` | Rating moyen des joueurs du coup | oui | Badge de contexte |
| `moves[].white` | Victoires blanches apres le coup | oui | Statistique du candidat |
| `moves[].draws` | Nulles apres le coup | oui | Statistique du candidat |
| `moves[].black` | Victoires noires apres le coup | oui | Statistique du candidat |
| `moves[].game` | Partie representative du coup | non | Exemple concret, carte de partie |
| `moves[].opening` | Ouverture atteinte apres le coup | non | Etiquette de transition |
| `topGames[]` | Parties de haut niveau | non | Partie de reference, RAG source |
| `recentGames[]` | Parties recentes | non | Evolution et actualite d'une idee |
| `history[]` | Resultats par mois | non | Courbe de popularite et tendances |

### Endpoints Non Utilises

| Endpoint / champ | Description | Statut | Inspiration produit |
| --- | --- | --- | --- |
| `/player` | Statistiques d'un joueur donne | non utilise | Conseil personnalise base sur l'historique |
| `/masters/pgn/{gameId}` | PGN complet d'une partie de Masters | non utilise | Partie annotee dans le coach |
| `recentGames[].year/month` | Date des parties recentes | non utilise | Distinguer mode historique et tendance actuelle |
| `topGames[].white/black` | Joueurs d'une partie de reference | non utilise | Explication concrete avec les joueurs |

## Contrat Runtime

Host: `explorer.lichess.org`. Le token vient de `LICHESS_TOKEN`. Une reponse invalide, vide,
interdite, en timeout ou une API indisponible utilise le seed local et ajoute un fallback visible.
Les buckets de rating sont `0`, `1000`, `1200`, `1400`, `1600`, `1800`, `2000`, `2200`, `2500`.

Le contrat detaille et les transformations sont implementes dans
`backend/app/services/lichess.py` et couverts par `backend/tests/test_lichess.py`.
