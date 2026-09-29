# POC Agent d'ouvertures FFE

Ce depot contient le POC d'un agent intelligent pour accompagner les jeunes espoirs de la Federation Francaise des Echecs dans l'apprentissage des ouvertures.

## Documentation

- [Contexte agentique de reference](docs/AGENT_CONTEXT.md)
- [MVP et criteres d'acceptation](docs/MVP.md)
- [Architecture cible](docs/ARCHITECTURE.md)
- [Donnees et sources](docs/DATA.md)
- [UX Angular](docs/UX.md)
- [Plan de livraison](docs/PLAN.md)
- [Risques et mitigations](docs/RISKS.md)
- [Cahier des charges](docs/PROJECT.md)

Les agents doivent commencer par `docs/AGENT_CONTEXT.md` avant toute proposition ou implementation. Les decisions structurantes sont documentees dans `docs/adr/`. Les anciens plans non maintenus sont conserves dans `docs/archive/`.

## Objectif du POC

L'application doit proposer une interface Angular avec echiquier interactif et un backend FastAPI capable d'analyser une position d'echecs avec :

- identification de la position en FEN ;
- donnees d'ouvertures Lichess ;
- recherche vectorielle Milvus ;
- stockage MongoDB ;
- orchestration LangGraph ;
- evaluation Stockfish hors theorie ;
- videos YouTube pertinentes.

## Stack cible

- Frontend : Angular, `ngx-chessboard` ou `material-chessboard`
- Backend : FastAPI, Python 3.12, LangGraph
- Donnees : MongoDB, Milvus
- Moteur : Stockfish
- APIs : Lichess, YouTube
- Execution locale : `docker compose`
