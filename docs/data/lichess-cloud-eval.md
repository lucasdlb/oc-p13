# Lichess Cloud Evaluation

Cloud Eval est un candidat non implemente. Le backend utilise actuellement Stockfish local pour
l'evaluation hors theorie.

## Contrat Envisage

`GET https://lichess.org/api/cloud-eval` accepte un FEN et un `multiPv`, puis renvoie une profondeur,
des noeuds et des PV en UCI. Le score est du point de vue des Blancs; Stockfish local renvoie un
score du point de vue du trait. Toute integration doit normaliser la perspective avant affichage.

## Endpoint Et Parametres

| Endpoint | Usage actuel | Parametres associes |
| --- | --- | --- |
| `GET /api/cloud-eval` | non implemente; candidat voie rapide Stockfish | `fen`, `multiPv`, `variant` |

Le POC n'utilise pas encore Cloud Eval. Ces parametres changent la position evaluee, la variante et
le nombre de PV demandees; ils ne changent pas le schema general de la reponse.

| Parametre | Description | Inspiration produit |
| --- | --- | --- |
| `fen` | Position a evaluer | voie rapide pour les positions connues |
| `multiPv` | Nombre de variantes demandees, jusqu'a 5 disponibles | afficher plusieurs continuations |
| `variant` | Variante Lichess, par defaut `standard` | variantes hors scope du POC |

## Catalogue Des Champs

| Champ | Description | Recupere ? | Inspiration produit |
| --- | --- | --- | --- |
| `fen` | FEN reduite de la position evaluee | non | Verifier que la reponse correspond a la position |
| `knodes` | Milliers de noeuds recherches | non | Afficher la profondeur de preuve |
| `depth` | Profondeur de l'evaluation pre-calculee | non | Comparer cloud et moteur local |
| `pvs[].cp` | Score en centipawns, point de vue Blancs | non | Evaluation profonde |
| `pvs[].mate` | Distance vers un mat | non | Detection de tactique forcee |
| `pvs[].moves` | Variante principale en coups UCI | non | Afficher plusieurs continuations |
| `404 error` | Position absente de la base | non | Fallback explicite vers Stockfish local |

## Fallback

Une reponse 200 pourrait servir de voie rapide et etre cachee sous une cle distincte. Un 404, une
erreur ou un timeout reviendrait a Stockfish local. Cette integration doit rester optionnelle,
mesuree et documentee dans une ADR avant implementation.
