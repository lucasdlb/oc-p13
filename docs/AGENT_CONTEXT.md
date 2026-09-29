# Contexte agentique du POC FFE

Ce document est la reference principale pour tout agent qui travaille sur ce depot. Il transforme le cahier des charges et le plan projet en contraintes operationnelles pour limiter les reinterpretations et rendre le travail agentique presque deterministe.

## Ordre de lecture obligatoire

Avant toute proposition ou implementation, lire dans cet ordre :

1. `docs/AGENT_CONTEXT.md`
2. `docs/MVP.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DATA.md` si la tache touche les sources, MongoDB, Milvus ou les caches
5. `docs/UX.md` si la tache touche le frontend ou l'experience utilisateur
6. `docs/PLAN.md` si la tache touche l'ordre de livraison
7. `docs/RISKS.md` si la tache touche un fallback ou une mitigation
8. `GLOSSARY.md`
9. Les ADRs pertinents dans `docs/adr/`
10. `docs/PROJECT.md` seulement pour verifier la demande client brute

## Objectif produit

Livrer en deux semaines un POC executable localement qui accompagne des jeunes joueurs d'echecs dans l'apprentissage des ouvertures. Le succes prioritaire est un parcours de demonstration complet : l'utilisateur joue des coups, obtient l'ouverture identifiee, des coups recommandes, une explication adaptee a son niveau, des statistiques Lichess, une video ou un fallback YouTube, et une evaluation Stockfish si la position sort de la theorie.

La valeur produit prime sur l'exhaustivite technique. Les briques techniques demandees doivent rester visibles et integrees, mais un parcours client fluide est prioritaire en cas de conflit.

## Technologies non negociables

Les technologies suivantes font partie du livrable cible et ne doivent pas etre remplacees silencieusement :

- Angular pour le frontend.
- FastAPI pour le backend.
- Docker Compose pour l'execution locale.
- Stockfish pour l'evaluation moteur.
- LangGraph pour l'orchestration agentique.
- MongoDB pour les donnees applicatives, sessions, ouvertures et caches.
- Milvus pour la recherche vectorielle.
- Lichess API pour les statistiques et donnees live.
- YouTube API pour les videos explicatives.

Un fallback est autorise uniquement s'il est documente dans `docs/ARCHITECTURE.md` ou dans un ADR, avec sa condition d'activation, son impact demo, et la maniere de revenir a la technologie cible.

## Workflow obligatoire avant implementation

Aucune phase majeure d'implementation ne commence directement par du code.

Pour chaque phase, l'agent doit :

1. Lire les documents obligatoires.
2. Identifier les decisions deja fermees et les decisions encore ouvertes.
3. Faire une recherche cadree si la phase touche une zone ouverte.
4. Proposer ou mettre a jour un ADR lorsque la decision est structurante.
5. Demander validation utilisateur explicite.
6. Implementer seulement apres validation.

Les zones ouvertes pour recherche cadree sont :

- Provider LLM.
- Modele d'embeddings.
- Sources pedagogiques documentaires.
- Librairie d'echiquier Angular.

Les agents peuvent rechercher d'autres technologies seulement si elles enrichissent une de ces zones sans remettre en cause l'architecture cible.

## Validation humaine

Le passage d'une phase majeure a la suivante requiert une validation utilisateur explicite. Une phase majeure inclut notamment :

- choix de librairie frontend structurante ;
- choix LLM ou embeddings ;
- schema de donnees MongoDB ou Milvus ;
- integration LangGraph ;
- integration d'une API externe ;
- modification d'un fallback documente ;
- changement de priorite MVP.

## Comportement attendu des agents

Les agents doivent executer le cadre existant plutot que reinventer le projet. En cas d'ambiguite, ils doivent expliciter l'ambiguite, proposer une recommandation, puis attendre validation si la decision impacte l'architecture, les donnees, les couts ou la demonstration.

Les agents ne doivent pas :

- remplacer une technologie non negociable sans ADR ;
- ajouter une nouvelle dependance structurante sans recherche et validation ;
- privilegier une preuve technique au detriment du parcours complet ;
- generer des explications d'echecs non rattachees aux sources disponibles ;
- ignorer les conditions d'utilisation ou licences des sources de donnees.

## Reponse du coach IA

Le coach IA doit etre contraint par les sources. Il peut reformuler et pedagogiser, mais ne doit pas inventer de faits sur une ouverture, une statistique ou une evaluation.

La reponse doit pouvoir indiquer clairement ce qui vient de :

- l'ouverture identifiee localement ;
- Lichess ;
- le contexte documentaire RAG ;
- Stockfish ;
- YouTube ou son fallback.

Le niveau pedagogique est adaptatif avec trois niveaux fixes : `debutant`, `intermediaire`, `avance`.

## Politique sources et licences

Chaque source utilisee doit etre documentee avec :

- URL ;
- role dans le produit ;
- licence ou conditions d'utilisation ;
- statut : `valide`, `a verifier`, ou `refuse` ;
- justification courte.

Une source avec statut `a verifier` peut etre utilisee pour exploration locale, mais ne doit pas devenir une dependance demo centrale sans validation.

## Documentation attendue

Le paquet documentaire initial est :

- `docs/AGENT_CONTEXT.md` : contrat agentique et regles d'execution.
- `docs/MVP.md` : perimetre du POC, criteres d'acceptation, priorites.
- `docs/ARCHITECTURE.md` : architecture cible, flux, fallbacks autorises.
- `docs/DATA.md` : sources, donnees, MongoDB, Milvus et caches.
- `docs/UX.md` : interface Angular et parcours utilisateur.
- `docs/PLAN.md` : ordre de livraison et phases.
- `docs/RISKS.md` : risques, mitigations et escalades.
- `GLOSSARY.md` : vocabulaire metier.
- `docs/adr/` : decisions structurantes.

`docs/PROJECT.md` conserve le brief client brut. `docs/archive/` conserve les anciens plans non maintenus. Ces fichiers ne doivent pas redevenir des sources de verite operationnelles.
