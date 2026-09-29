# Plan de livraison

Ce document est la source de verite pour l'ordre de livraison et les phases de travail. Il ne remplace pas les ADRs : toute decision structurante doit rester documentee dans `docs/adr/`.

## Regle de phase

Chaque phase majeure suit le workflow defini dans `docs/AGENT_CONTEXT.md` : research si necessaire, ADR ou mise a jour documentaire, validation utilisateur, puis implementation.

## Ordre d'implementation recommande

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

## Planning indicatif deux semaines

| Jour | Objectif |
| --- | --- |
| 1 | Cadrage technique, validation MVP, structure repo, squelettes FastAPI et Angular, compose minimal |
| 2 | Echiquier Angular, generation FEN/PGN/UCI, `/health`, `/api/analyze-position` mocke |
| 3 | Ingestion ou seed `lichess-org/chess-openings`, stockage MongoDB, premier matching |
| 4 | Setup Milvus minimal, choix embeddings, indexation corpus limite |
| 5 | Source pedagogique validee, nettoyage texte, recherche RAG |
| 6 | Lichess Opening Explorer, affichage stats, cache MongoDB |
| 7 | Stockfish local, fallback hors theorie, format de reponse stabilise |
| 8 | LangGraph autour des services stabilises, prompt coach contraint |
| 9 | YouTube API ou fallback, affichage videos |
| 10 | UI responsive, panneaux analyse, stats, videos |
| 11 | Docker Compose complet, variables d'environnement, script d'ingestion |
| 12 | Tests backend, frontend de base, integration critique |
| 13 | Donnees de seed, preparation demo, documentation d'execution |
| 14 | Repetition demo, bugfix final, livraison |

## Definition de termine pour une phase

Une phase est terminee lorsque :

- les criteres associes au MVP restent satisfaits ou explicitement inchanges ;
- les fallbacks utilises sont documentes ;
- les decisions nouvelles sont capturees en ADR si structurantes ;
- la commande de verification pertinente a ete lancee ou son absence justifiee ;
- l'utilisateur a valide le passage a la phase suivante.
