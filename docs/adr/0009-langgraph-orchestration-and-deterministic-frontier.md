# Orchestration LangGraph et frontiere deterministe

Status: accepted target decision (2026-10-06; not yet implemented)

Accepted after review of the product architecture trajectory. This ADR supersedes the
LangGraph deferral clauses in ADR 0006 and ADR 0007; the imperative services and their
deterministic tests remain authoritative.

Ce document propose le cablage LangGraph attendu par le cahier des charges (ADR 0002,
`docs/AGENT_CONTEXT.md`) sans transformer le POC en agent autonome. Il precise et, sur les
points listes, remplace des clauses de l'ADR 0006 et de l'ADR 0007.

## Etat d'implementation

Le runtime actuel reste imperatif : les routes FastAPI appellent directement les services
stabilises et `langgraph` n'est pas encore une dependance de `pyproject.toml`. Cette ADR accepte
la trajectoire cible, mais ne doit pas etre lue comme la description du runtime present.

## Contexte

LangGraph est une technologie non negociable du livrable. Or l'etat decide est inverse :
l'ADR 0006 dit « LangGraph est reporte », l'ADR 0007 dit « Pas de LangGraph », et les services
`RagService` / `CoachService` ne doivent pas importer `langgraph`. Il faut donc concilier deux
exigences : livrer une orchestration LangGraph visible, et ne pas degrader la fiabilite, la
tracabilite et la testabilite acquises par le pipeline imperatif.

Deux constats cadrent la decision :

- « L'utilisation de LangChain ou LangGraph ne rend pas automatiquement le produit agentique.
  Un graphe dont le chemin est entierement ecrit a l'avance reste principalement un workflow
  deterministe. » (principe conserve dans cette ADR)
- Un graphe dont chaque noeud ne fait qu'appeler un service deja stabilise change tres peu le
  comportement produit : le gain est structurel (etat, branches, fallbacks, streaming), pas
  comportemental.

## Decision

1. **LangGraph est introduit comme module d'orchestration separe.** Le graphe vit dans un
   module dedie (par exemple `backend/app/orchestration/`) et reste la seule couche a importer
   `langgraph`. `RagService`, `CoachService` et les autres services restent imperatifs et
   n'importent pas `langgraph`. Cette clause de l'ADR 0006 est conservee.

2. **V1 = DAG deterministe « passe-plat ».** Un noeud par etape de l'actuel pipeline, chaque
   noeud delegant a un service deja stabilise. Le comportement produit doit rester inchange
   (meme reponse, memes fallbacks, memes labels diagnostiques).

3. **Le chemin imperatif reste la reference.** Les tests ciblent les services, pas le graphe.
   Le graphe peut etre desactive par configuration ; le pipeline imperatif demeure le filet de
   securite et l'implementation de reference.

4. **Minima agentiques.** Au moins un point de decision conditionnel reel est conserve dans le
   graphe, pour ne pas livrer une simple facade :
   - routeur d'intention ou de phase donnant un `retrieval_plan` construit par le code ;
   - choix Lichess / Stockfish selon la sortie de theorie (`in_theory`).
   Le reste du chemin reste deterministe.

5. **Noeuds minces.** Un noeud n'accede jamais directement aux API externes, a Milvus, a
   MongoDB ou a Stockfish ; il appelle un service. Aucune logique metier nouvelle ne doit
   apparaitre dans le graphe.

6. **Fallbacks comme aretes conditionnelles.** Les fallbacks documentes (ADR 0006,
   `docs/ARCHITECTURE.md`) sont representes par des aretes conditionnelles et conservent leurs
   labels diagnostiques (`llm_coach_unavailable`, `llm_coach_timeout`, ...).

7. **Evolution incrementale.** Les paliers a venir restent : DAG deterministe -> conditions
   documentees -> MVP agentique -> planner de retrieval complet. Le planner complet n'est
   introduit qu'apres stabilisation du chemin coach et mise a jour d'un ADR.

## Ce qui est remplace dans les ADR existants

- ADR 0006, clause « LangGraph est reporte » : remplacee par la presente decision. La clause
  « `RagService`/`CoachService` ne doivent pas importer `langgraph` » reste en vigueur.
- ADR 0007, decision 11 « Pas de LangGraph » : reformulee en « LangGraph n'entre pas dans
  `CoachService` ; l'orchestration est un module separe ». Le reste de l'ADR 0007 est inchange.

## Alternatives considerees

- **Rester strictement imperatif.** Rejete : ne satisfait pas visiblement la technologie non
  negociable pour la livraison, alors que le cout du passe-plat est faible.
- **Tool calling dynamique (boucle de type ReAct).** Rejete pour le POC : latence, cout,
  testabilite et controle degrades. Une investigation bornee est documentee dans l'ADR 0010.
- **Architecture multi-agents.** Rejetee : trop complexe pour le POC.

## Consequences

- Le livrable expose une orchestration LangGraph sans changer le comportement produit.
- La revendication de soutenance reste « agent specialise, hybride et contraint » ; un DAG
  fixe n'est pas presente comme un agent autonome.
- Le graphe ajoute une indirection et une dependance : il doit rester mince et testable par
  ses services sous-jacents.
- Toute logique metier qui apparait dans un noeud est un bug de conception a corriger.

## References

- `docs/ARCHITECTURE.md` : implementation actuelle et orchestration cible.
- `docs/adr/0010-bounded-agentic-investigation-tool.md` : investigation optionnelle et bornee.
- `docs/adr/0002`, `docs/adr/0006`, `docs/adr/0007`.
