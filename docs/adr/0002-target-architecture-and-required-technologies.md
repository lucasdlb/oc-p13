# Architecture cible et technologies requises

Status: accepted

Le POC conserve Angular, FastAPI, Docker Compose, Stockfish, LangGraph, MongoDB, Milvus, Lichess API et YouTube API comme technologies non negociables, car elles sont demandees par le cahier des charges ou necessaires a la demonstration client. Les fallbacks sont autorises uniquement s'ils sont documentes avec leur condition d'activation et ne remplacent pas silencieusement la cible.

## Consequences

- Les agents ne peuvent pas remplacer une brique requise par une alternative plus simple sans ADR.
- Les integrations peuvent etre limitees pour tenir le delai, mais leur presence et leurs limites doivent rester visibles.
- Les librairies precisees autour de ces briques doivent etre challengees avant chaque phase d'implementation.
