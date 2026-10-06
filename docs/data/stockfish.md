# Stockfish

Stockfish est la source de verite des faits moteur hors theorie. L'adapter actuel lance le binaire
local avec `position fen` puis `go depth <n>`. La profondeur par defaut est 12 et la profondeur
effective reste bornee par les settings.

## Reponse Actuelle

```json
{
  "status": "ok",
  "best_move": "g1f3",
  "score": {"type": "cp", "value": 24},
  "depth": 12
}
```

Les echecs renvoient `status: unavailable` avec une raison (`binary_not_found`, `process_error`,
`timeout` ou `invalid_uci_output`). Seules les reponses `ok` sont mises en cache. Le score UCI reste
du point de vue du trait; le frontend ne le normalise pas encore vers le point de vue des Blancs.

## Commandes Et Parametres UCI

Stockfish n'est pas une API HTTP : le backend lui parle avec le protocole UCI.

| Commande / option | Utilise ? | Parametres associes | Effet |
| --- | --- | --- | --- |
| `uci` | oui | aucun | Handshake et liste des options moteur |
| `isready` | oui | aucun | Attend que le moteur soit pret |
| `position fen` | oui | `fen` | Definit la position a evaluer |
| `go depth` | oui | `depth` | Cherche jusqu'a une profondeur bornee |
| `go movetime` | non | millisecondes | Budget temps fixe |
| `go nodes` | non | nombre de noeuds | Budget de calcul fixe |
| `go searchmoves` | non | liste de coups UCI | Evalue seulement certains coups |
| `setoption name MultiPV` | non | nombre de variantes | Produit plusieurs candidats |
| `setoption name UCI_ShowWDL` | non | `true` / `false` | Ajoute les probabilites WDL |
| `setoption name Threads` | non | nombre de threads | Controle la parallelisation |
| `setoption name Hash` | non | memoire en MB | Controle la table de transposition |
| `setoption name UCI_LimitStrength` | non | `true` / `false` | Simule une force reduite |
| `setoption name UCI_Elo` | non | Elo cible | Adapte la force simulee |

Le POC utilise aujourd'hui seulement `position fen` et `go depth <settings.depth>`. Toute activation
de `MultiPV`, `movetime`, `searchmoves`, `UCI_ShowWDL`, `Threads` ou `Hash` doit rester bornee par
la configuration backend et entrer dans la cle de cache Stockfish si elle change le resultat.

## Catalogue Des Champs UCI

| Champ | Description | Recupere ? | Inspiration produit |
| --- | --- | --- | --- |
| `depth` | Profondeur nominale atteinte | partiel | Indicateur de confiance; aujourd'hui profondeur demandee |
| `seldepth` | Profondeur selective maximale | non | Fiabilite de la recherche |
| `multipv` | Rang de la variante quand MultiPV est actif | non | Afficher plusieurs candidats |
| `score cp` | Evaluation en centipawns | oui | Comparer les positions |
| `score mate` | Distance vers un mat force | oui si fourni | Signaler une tactique forcee |
| `wdl` | Estimation victoire/nulle/defaite | non | Barres de probabilite |
| `nodes` | Noeuds examines | non | Mesurer l'effort de recherche |
| `nps` | Noeuds par seconde | non | Diagnostic performance |
| `time` | Temps de recherche en millisecondes | non | Confiance et budget UI |
| `hashfull` | Utilisation de la table de transposition | non | Diagnostic de stabilite |
| `pv` | Variante principale en coups UCI | non | Continuation interactive |
| `bestmove` | Meilleur coup choisi | oui | Recommandation principale |
| `ponder` | Coup attendu en reponse | non | Suggestion de suite |

Le moteur peut aussi fournir `currmove`, `currmovenumber`, `refutation`, `currline` et `info string`;
ils sont ignores par le POC car ils sont surtout utiles au suivi temps reel et au diagnostic.

## Evolutions Candidates

- afficher une PV courte et plusieurs candidats avec MultiPV;
- comparer le coup joue avec le choix moteur;
- expliquer une perte en fractions de pion;
- afficher WDL et un indicateur de confiance;
- exiger une PV et une bascule d'evaluation avant d'affirmer un « piege ».

Les budgets doivent rester bornes. Voir les ADR 0010 et 0011 pour les decisions de trajectoire.
