# Outil d'investigation agentique borne

Status: proposed (2026-10-05; not yet implemented)

Cette decision ajoute un point d'agentivite reel au graphe LangGraph sans transformer le
parcours standard en boucle ReAct ouverte. Elle complete l'ADR 0009.

## Contexte

Le parcours deterministe sait deja valider une position, identifier une ouverture, interroger
Lichess, lancer Stockfish, recuperer de la prose RAG et produire une explication. Certaines
questions meritent cependant une investigation supplementaire : comprendre la logique d'un plan,
anticiper une suite a deux coups, ou expliquer le developpement futur d'une strategie.

Le systeme doit pouvoir decider qu'il ne dispose pas encore de suffisamment de contexte, appeler
des outils supplementaires, observer leurs resultats, puis poursuivre la synthese. Cette boucle
doit rester limitee pour conserver la testabilite, la latence et la tracabilite du POC.

## Decision

1. **Ajouter un outil logique `investigate_position`.** Ce n'est pas un nouvel acces externe :
   c'est une capacite d'orchestration qui regroupe un petit menu d'outils existants :
   `search_opening_tree`, `get_lichess_stats`, `evaluate_stockfish` et
   `search_opening_context`.

2. **Le graphe ou le noeud d'investigation decide du declenchement.** Le routeur recoit la
   question, le niveau pedagogique, l'intention, la confiance, la sortie de theorie et le
   contexte deja collecte. Il peut choisir `investigate_position` lorsque l'information
   supplementaire apporte une valeur pedagogique identifiable.

3. **L'execution est une boucle ReAct courte et bornee.** La boucle alterne :

   ```text
   decide -> call one permitted tool -> observe -> decide again -> stop
   ```

   Limites par defaut : au plus 3 tours, au plus 4 appels d'outils, un budget temporel dedie,
   et pas de recursion vers `investigate_position`. Les appels independants sont parallelises
   lorsque le plan le permet.

4. **Le menu d'outils est ferme.** Le modele ne fabrique pas d'outil et ne choisit pas une URL
   arbitraire. Chaque appel est valide par le backend, journalise et associe a un type de preuve.

5. **La profondeur d'echecs reste locale.** L'arbre fournit les enfants directs et au plus une
   suite courte ; Stockfish peut utiliser `MultiPV` et une PV courte ; Lichess peut comparer la
   position courante et les candidats ; le RAG explique les plans et les idees associes. Les
   descendants profonds restent exclus par defaut.

6. **L'agent peut choisir le budget Stockfish.** Dans `investigate_position`, il peut demander
   une profondeur, un `movetime`, un nombre de variantes `MultiPV` ou une combinaison adaptee a
   la question : analyse legere pour une question generale, analyse plus profonde pour une
   question tactique ou un piege. Le backend valide et borne toujours ces parametres ; l'agent
   ne peut pas imposer une profondeur ou une duree illimitee.

   Exemple de politique :

   ```text
   question generale       -> depth 10, MultiPV 2, budget court
   plan strategique         -> depth 14, MultiPV 3, PV courte
   tactique / piege         -> depth 18, MultiPV 3, movetime borne
   ```

   La profondeur demandee est un budget de calcul, pas une preuve de justesse. Une conclusion
   tactique reste soumise a la stabilite de l'evaluation, a la PV et au controle de coherence.

7. **Un piege exige une preuve Stockfish.** Le coach peut annoncer un piege uniquement si une PV
   valide montre la sequence et qu'une bascule d'evaluation ou une consequence tactique est
   constatee. Sans cette preuve, le texte doit dire « suite possible », « risque » ou « idee a
   verifier », jamais affirmer « piege ».

8. **La sortie est un `InvestigationContext` source.** Elle separe au minimum :

   - `current_position` ;
   - `candidate_lines` ;
   - `lichess_comparison` ;
   - `strategic_prose` ;
   - `trap_evidence` ;
   - `next_development` ;
   - `tools_used` et `stop_reason`.

   Le `CoachService` ne recoit que ce contexte structure et source. Il ne relance pas lui-meme
   les outils.

9. **Fallback conservateur.** Si la boucle depasse son budget, si un outil est indisponible ou
   si les preuves sont contradictoires, le graphe arrete l'investigation et synthétise avec le
   contexte deja valide. L'analyse ne tombe jamais en erreur pour une investigation incomplete.

## Exemples de declenchement

- Question « Pourquoi ce coup ? » avec plusieurs candidats proches : Stockfish MultiPV,
  statistiques Lichess et prose strategique sont compares.
- Question « Y a-t-il un piege dans cette ligne ? » : arbre des continuations directes puis
  Stockfish confirme ou invalide la sequence a deux coups.
- Question « Quel est le plan apres cette strategie ? » : l'arbre explore les continuations
  directes et le RAG recupere la prose conditionnelle correspondante.
- Question factuelle deja presente dans l'etat, par exemple l'evaluation Stockfish :
  `no_investigation`.

## Frontiere deterministe / agentique

- Agentique : decision de creuser, ordre des observations, arret de la boucle.
- Deterministe : validation des appels, legalite, budget, profondeur, scores Stockfish,
  provenance, distinction position courante / suite possible.
- LLM : formulation pedagogique finale, strictement bornee par `InvestigationContext`.

## Consequences

- Le systeme possede une agentivite observable : il peut decider de chercher davantage puis
  utiliser l'observation pour choisir l'appel suivant.
- Le parcours standard reste court et proche du DAG actuel, car l'outil est optionnel.
- La complexite et la latence augmentent uniquement sur les questions qui declenchent
  l'investigation.
- Les tests peuvent rejouer une boucle avec un faux registre d'outils et des observations
  deterministes, sans Ollama, Lichess ou Stockfish reels.
- Le comportement de « piege » est plus strict que la prose RAG : une affirmation tactique
  necessite une preuve moteur.

## Alternatives considerees

- **Investigation toujours active** : rejetee, car elle augmente la latence et le cout de toutes
  les analyses.
- **Tool calling totalement libre** : reporte, car il n'a ni budget ni trajectoire testable.
- **Rules uniquement sans boucle** : conserve comme fallback, mais insuffisant pour demontrer une
  agentivite reelle.

## References

- `docs/adr/0009-langgraph-orchestration-and-deterministic-frontier.md` pour la frontiere deterministe.
- `docs/ARCHITECTURE.md` pour les services et fallbacks existants.
- `docs/data/stockfish.md` pour le contrat Stockfish.
- `docs/data/milvus.md` et `docs/data/sources.md` pour l'arbre d'ouvertures, la separation arbre/RAG et les contraintes de retrieval.
