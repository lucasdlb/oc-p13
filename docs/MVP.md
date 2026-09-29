# MVP du POC FFE

Le MVP doit prouver qu'un jeune joueur peut utiliser l'application pour comprendre une ouverture et recevoir une aide fiable pendant une sequence de demonstration.

## Priorite

La priorite est le parcours complet de demonstration, pas l'exhaustivite technique. Toutes les briques demandees doivent etre representees, mais les implementations peuvent etre limitees si les limites sont documentees et si le parcours reste coherent.

## Parcours de demonstration cible

1. L'utilisateur ouvre l'application via `docker compose`.
2. L'utilisateur joue des coups sur un echiquier Angular.
3. Le frontend transmet FEN, PGN, coups UCI et niveau pedagogique au backend.
4. Le backend identifie l'ouverture si elle est connue.
5. Le backend recupere ou simule de maniere documentee les meilleurs coups theoriques.
6. Le backend recupere les statistiques Lichess disponibles.
7. Le backend recupere un contexte pedagogique via Milvus.
8. Le backend appelle Stockfish si la position sort de la theorie ou si le scenario l'exige.
9. Le backend recupere des videos YouTube ou renvoie un lien de recherche fallback.
10. Le coach produit une explication contrainte par les donnees disponibles.
11. Le frontend affiche ouverture, coups recommandes, explication, stats, evaluation et videos.

## Scenarios obligatoires

### Scenario 1 : ouverture connue

- Jouer `1. e4`.
- Identifier une ouverture ou famille d'ouverture.
- Afficher des coups candidats.
- Donner une explication pedagogique adaptee au niveau choisi.
- Proposer une video ou un fallback YouTube.

### Scenario 2 : ligne theorique

- Jouer `1. e4 e5 2. Nf3 Nc6 3. Bb5`.
- Identifier l'Espagnole / Ruy Lopez si les donnees ingerees le permettent.
- Afficher les idees principales pour les blancs et les noirs.
- Afficher des statistiques Lichess si disponibles.

### Scenario 3 : sortie de theorie

- Jouer une suite marginale ou inconnue du matching local.
- Declencher Stockfish.
- Expliquer que la position sort des lignes connues.
- Proposer un plan de correction ou un coup candidat selon l'evaluation.

### Scenario 4 : preuve technique

- Montrer l'application lancee avec `docker compose`.
- Montrer les services backend, frontend, MongoDB et Milvus actifs.
- Montrer au moins une ingestion ou seed de donnees.
- Montrer un appel ou fallback Lichess et YouTube.

## Criteres d'acceptation

- `docker compose` lance l'environnement local documente.
- Le frontend Angular permet de jouer des coups et d'envoyer une position au backend.
- `POST /api/analyze-position` renvoie une reponse structuree exploitable par l'UI.
- La reponse distingue ouverture, coups recommandes, statistiques, contexte RAG, Stockfish et videos.
- Le niveau pedagogique accepte au moins `debutant`, `intermediaire`, `avance`.
- Les limites, fallbacks et sources non validees sont visibles dans la documentation.
- Le coach ne presente pas une information non sourcee comme un fait.

## Hors scope initial

- Authentification utilisateur.
- Persistance long terme de comptes joueurs.
- Entrainement personnalise sur plusieurs semaines.
- Couverture exhaustive de toutes les ouvertures.
- Scraping massif de sources incertaines.
- Optimisation de performance hors besoin demo.

## Priorites d'implementation

1. Contrat API et reponse mockee credible.
2. Echiquier Angular connecte au backend.
3. Matching local d'ouvertures avec donnees seed.
4. Lichess stats ou fallback documente.
5. Stockfish pour sortie de theorie.
6. Milvus avec corpus pedagogique limite.
7. LangGraph pour orchestrer le flux stabilise.
8. YouTube API ou fallback de recherche.
9. Docker Compose complet.
10. Polish demo et documentation d'execution.
