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

- Frontend : Angular, `@lichess-org/chessground` et `chess.js`
- Backend : FastAPI, Python 3.12, LangGraph
- Donnees : MongoDB, Milvus
- Moteur : Stockfish
- APIs : Lichess, YouTube
- Execution locale : `docker compose`

## Configuration locale

Les parametres non secrets vivent dans `config.toml`. Lichess Opening Explorer peut etre active pour tenter les statistiques live, avec fallback seed si le service refuse ou ne repond pas :

```toml
[lichess]
enabled = true
base_url = "https://explorer.lichess.org"
timeout_seconds = 2.0
```

Le token Lichess est un secret et doit rester dans `.env`, jamais dans `config.toml` :

```bash
cp .env.example .env
```

Puis renseigner :

```text
LICHESS_TOKEN=<votre-token-lichess>
```

Generer le token depuis `https://lichess.org/account/oauth/token`. D'apres la specification OpenAPI Lichess, Opening Explorer utilise OAuth2 sans scope specifique pour `/lichess` et `/masters`.

Quand `enabled = false`, quand `LICHESS_TOKEN` manque, ou quand Lichess est indisponible, non autorise, invalide ou vide, le backend renvoie les statistiques seed `seed-lichess-cache` et expose le fallback dans `fallbacks_used`.

Redemarrer FastAPI apres modification de `.env` ou `config.toml`, car les settings sont charges au demarrage.
