# Risques et mitigations

Ce document est la source de verite pour les risques projet, leurs mitigations et leurs conditions d'activation. Les fallbacks techniques detailles restent references dans `docs/ARCHITECTURE.md` ou dans un ADR.

| Risque | Impact | Mitigation |
| --- | --- | --- |
| Milvus prend trop de temps a configurer | Retarde RAG et compose complet | Partir du compose officiel, limiter le corpus, documenter un RAG vide explicite si necessaire |
| Corpus pedagogique trop gros ou sale | Retarde ingestion et degrade reponses | Limiter aux ouvertures de demo, chunker peu, valider les sources avant ingestion centrale |
| Cle YouTube absente ou quota depasse | Pas de metadata videos | Utiliser un lien de recherche YouTube pre-rempli et l'indiquer comme fallback |
| Lichess indisponible pendant demo | Stats live absentes | Utiliser cache MongoDB ou donnees seedees documentees |
| Stockfish difficile a packager | Sortie de theorie non couverte | Installer le binaire dans l'image backend et utiliser `python-chess.engine` |
| LangGraph complexifie trop tot | Ralentit l'implementation du parcours | Stabiliser les services imperatifs avant orchestration LangGraph |
| Reponses IA hallucinees | Perte de confiance demo | Contraindre le coach aux donnees structurees, RAG, Lichess et Stockfish ; fallback systematique vers le template source avec un label diagnostique (`llm_coach_unavailable`, `llm_coach_timeout`, `llm_coach_empty`, `llm_coach_too_long` ou `llm_coach_source_metadata`) si le LLM local echoue |
| Librairie echiquier incompatible | Bloque le frontend | Recherche cadree avant choix et fallback vers une autre librairie Angular |
| Licences de sources incertaines | Risque livraison/client | Statut strict `valide`, `a verifier`, `refuse`; pas de source centrale non validee |
| Trop de docs divergentes | Agents prennent des decisions contradictoires | Un role par document, `AGENT_CONTEXT.md` comme point d'entree, archives non maintenues |

## Regle d'escalade

Si un risque menace le parcours complet de demonstration, l'agent doit le signaler explicitement, recommander un fallback documente, puis attendre validation utilisateur avant de changer le plan.
