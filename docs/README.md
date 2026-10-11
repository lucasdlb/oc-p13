# Documentation

Index de la documentation du POC. Chaque document a un role unique; les decisions durables sont dans `adr/`.

## Pour Les Humains

| Besoin | Document |
| --- | --- |
| Lancer le projet, configurer l'environnement, tester | [`../README.md`](../README.md) |
| Preparer la video de demonstration | [`DEMO.md`](DEMO.md) |
| Comprendre le produit et ses criteres d'acceptation | [`MVP.md`](MVP.md) |
| Comprendre l'architecture et les contrats API | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Comprendre les donnees, sources, caches et licences | [`data/`](data/) |
| Consulter un contrat ou schema de donnees | [`data/README.md`](data/README.md) |
| Comprendre l'interface et le parcours utilisateur | [`UX.md`](UX.md) |
| Executer l'ingestion ou evaluer le RAG | [`runbooks/RAG.md`](runbooks/RAG.md) |
| Revoir l'interface avec des captures | [`runbooks/UI-WORKFLOW.md`](runbooks/UI-WORKFLOW.md) |
| Consulter les risques et fallbacks | [`RISKS.md`](RISKS.md) |
| Comprendre l'ordre de livraison | [`PLAN.md`](PLAN.md) |
| Consulter les metriques RAG | [`RAG-EVALUATION.md`](RAG-EVALUATION.md) |
| Consulter le brief client brut | [`PROJECT.md`](PROJECT.md) |
| Chercher un terme metier | [`GLOSSARY.md`](GLOSSARY.md) |
| Comprendre visuellement des concepts | [`explainers/`](explainers/) |
| Consulter l'étude de conception MCP vidéo | [`mcp-video-position-index.md`](mcp-video-position-index.md) |

## Pour Les Agents

1. Lire [`AGENT_CONTEXT.md`](AGENT_CONTEXT.md).
2. Utiliser sa table `Route By Task` pour ne charger que la branche utile.
3. Lire [`GLOSSARY.md`](GLOSSARY.md) si le travail touche le produit, le modele metier ou le texte utilisateur.
4. Charger les ADRs uniquement pour la decision ou le composant concerne.

## Decisions

Les ADRs sont numerotees et conservent les decisions de trajectoire. Une decision peut etre
acceptee avant son implementation et n'est pas figee pour toujours : une ADR ulterieure la remplace
explicitement lorsqu'elle le dit. Les documents courants distinguent l'implementation actuelle de
la cible acceptee.

- [`adr/0001-agentic-documentation-and-validation-workflow.md`](adr/0001-agentic-documentation-and-validation-workflow.md): workflow de travail et validation.
- [`adr/0002-target-architecture-and-required-technologies.md`](adr/0002-target-architecture-and-required-technologies.md): stack cible.
- [`adr/0003-data-sources-and-source-validation-policy.md`](adr/0003-data-sources-and-source-validation-policy.md): sources et licences.
- [`adr/0004-angular-chessboard-library.md`](adr/0004-angular-chessboard-library.md): echiquier Angular.
- [`adr/0005-mongodb-sessions-and-cache-policy.md`](adr/0005-mongodb-sessions-and-cache-policy.md): sessions et caches.
- [`adr/0006-rag-milvus-and-embeddings.md`](adr/0006-rag-milvus-and-embeddings.md): corpus et embeddings.
- [`adr/0007-llm-coach-synthesis.md`](adr/0007-llm-coach-synthesis.md): synthese du coach.
- [`adr/0008-coach-reference-language.md`](adr/0008-coach-reference-language.md): references interactives.
- [`adr/0009-langgraph-orchestration-and-deterministic-frontier.md`](adr/0009-langgraph-orchestration-and-deterministic-frontier.md): orchestration et frontiere agentique.
- [`adr/0010-bounded-agentic-investigation-tool.md`](adr/0010-bounded-agentic-investigation-tool.md): investigation bornee.
- [`adr/0011-evidence-pack-and-claim-verifier.md`](adr/0011-evidence-pack-and-claim-verifier.md): preuves et verification des claims.

L'ADR 0009 est implementee comme orchestration mince : LangGraph est cable pour les familles
Explorer, RAG et Coach REST, tandis que les services metier restent imperatifs et testables. Les ADR
0010 et 0011 sont actuellement des propositions de conception; elles ne decrivent pas des composants
deja presents dans le runtime.

## Organisation

- Documents de reference: fichiers directement sous `docs/`.
- Runbooks executables: `docs/runbooks/`.
- Decisions structurantes: `docs/adr/`.
