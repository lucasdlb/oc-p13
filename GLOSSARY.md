# POC Agent d'ouvertures FFE

Ce glossaire fixe le vocabulaire metier utilise par les agents et la documentation du POC. Il ne remplace pas les specs et ne contient pas de details d'implementation.

## Language

**Agent d'ouvertures**:
Assistant pedagogique qui analyse une position d'echecs dans la phase d'ouverture et aide le joueur a comprendre les coups, les plans et les ressources disponibles.
_Avoid_: chatbot, moteur d'analyse complet

**Jeune espoir**:
Joueur cible du POC, jeune competiteur accompagne par la Federation Francaise des Echecs dans sa progression.
_Avoid_: utilisateur generique, eleve

**Ouverture**:
Phase initiale d'une partie d'echecs, identifiable par une sequence de coups, un nom et parfois un code ECO.
_Avoid_: debut de partie quand le terme technique ouverture est attendu

**Ligne theorique**:
Sequence de coups connue et documentee dans les sources d'ouvertures utilisees par le POC.
_Avoid_: variante si le contexte parle seulement de reconnaissance generale

**Sortie de theorie**:
Position ou coup qui n'est plus couvert de maniere fiable par les sources d'ouverture disponibles.
_Avoid_: erreur, mauvais coup

**Position**:
Etat courant de l'echiquier, generalement represente par une FEN.
_Avoid_: plateau, configuration

**FEN**:
Notation textuelle qui represente une position d'echecs complete.
_Avoid_: identifiant FEN si le texte ne parle pas d'identifiant stable

**PGN**:
Notation de partie qui represente l'historique des coups dans une forme lisible.
_Avoid_: historique brut

**Coup UCI**:
Notation technique d'un coup, par exemple `e2e4`, utile pour les APIs et le matching.
_Avoid_: coup texte

**Coach IA**:
Composant qui reformule les resultats disponibles en explication pedagogique adaptee au niveau du joueur.
_Avoid_: LLM seul, agent libre

**Niveau pedagogique**:
Niveau d'explication demande au coach : `debutant`, `intermediaire`, ou `avance`.
_Avoid_: difficulte, elo estime

**Contexte pedagogique**:
Texte source retrouve pour expliquer une ouverture, un plan ou une idee strategique.
_Avoid_: contexte RAG si le public est non technique

**Fallback**:
Comportement documente qui degrade une fonctionnalite sans casser le parcours de demonstration.
_Avoid_: hack, contournement cache

**Chunk**:
Fragment de prose pedagogique, vectorise et stocke dans Milvus. Un chunk reste lie a sa source et a ses metadonnees (`eco_code`, `opening_name`, `chunk_title`) et porte son identite de page (`page_id`) et son ordre (`section_index`, `part_index`) pour permettre la reconstruction.
_Avoid_: document, passage

**Donnee structuree d'ouverture**:
Description formelle d'une ouverture (nom, code ECO, ligne de coups) utilisee pour le matching et la jointure `eco_code`, par opposition a la prose pedagogique. `lichess-org/chess-openings` est de ce type et n'est pas vectorisee dans Milvus.
_Avoid_: corpus, document

**Adaptateur d'ingestion**:
Composant qui transforme le contenu brut d'une source (TSV chess-openings, page Wikibooks) en chunks avec le schema commun. Un adaptateur par source, un seul pipeline de retrieval.
_Avoid_: connecteur, scraper

**Retrieval**:
Recherche par similarite semantique des chunks pertinents pour une position ou une question, dans la collection Milvus.
_Avoid_: recherche documentaire, lookup

**Attribution de source**:
Rattachement explicite d'une affirmation du coach a l'id de la source qui la justifie, valide cote backend avant affichage.
_Avoid_: citation, reference bibliographique
