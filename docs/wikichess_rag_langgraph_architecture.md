# WikiChess — Sources RAG et architecture agentique LangGraph

## 1. Objectif du système

WikiChess dispose déjà d’une couche structurée capable de fournir :

- la position courante ;
- le FEN ;
- l’historique des coups ;
- l’ouverture et la variante ;
- les statistiques Lichess ;
- la fréquence des coups par niveau ;
- les évaluations Stockfish ;
- les meilleurs coups ou principaux candidats ;
- le niveau du joueur ;
- le contexte conversationnel ;
- une éventuelle question précise du joueur.

Le rôle du RAG n’est donc pas de remplacer Stockfish ni Lichess.

Le RAG doit surtout apporter de la **prose pédagogique** :

- pourquoi un coup est joué ;
- quels sont les plans typiques ;
- quelles structures de pions apparaissent ;
- quelles pièces sont bien ou mal placées ;
- quelles cases sont importantes ;
- quelles ruptures de pions sont thématiques ;
- quelles erreurs sont fréquentes ;
- quelles transitions vers le milieu de jeu sont typiques ;
- quels compromis stratégiques existent.

L’orchestrateur LangGraph combine ensuite cette prose avec les données structurées pour produire une recommandation contextualisée.

---

## 2. Sources potentielles à ajouter au RAG

### 2.1 Chess Stack Exchange

Probablement l’une des meilleures sources pour enrichir le corpus pédagogique.

On y trouve naturellement :

- pourquoi un coup est joué ;
- pourquoi une variante fonctionne ;
- quels sont les plans dans une structure ;
- pourquoi une pièce est mal placée ;
- pourquoi une rupture de pion est importante ;
- quelles sont les idées derrière une ouverture ;
- comparaison de plusieurs plans ;
- erreurs typiques.

**Avantages :**

- beaucoup d’explications humaines ;
- questions très ciblées ;
- vocabulaire pédagogique naturel ;
- nombreux exemples avec suites de coups ;
- souvent plus conceptuel qu’une base d’ouverture classique.

**Licence :** les contributions Stack Exchange sont publiées sous CC BY-SA, avec une version dépendant de la date du contenu. Il faut conserver l’URL d’origine, l’auteur, la date, la licence applicable et les informations nécessaires à l’attribution.

**Usage recommandé :**

```json
{
  "opening_family": "French Defense",
  "variation": "Advance",
  "side": "black",
  "concepts": [
    "pawn_chain",
    "pawn_break",
    "pressure_on_d4"
  ],
  "moves": ["c5"],
  "content_type": "strategic_explanation",
  "difficulty": "intermediate",
  "source": "chess.stackexchange.com",
  "license": "CC BY-SA",
  "prose": "..."
}
```

### 2.2 Wikibooks Chess

Déjà présent dans le projet.

**Points forts :**

- nombreuses pages sur les ouvertures ;
- prose explicative ;
- variantes et sous-variantes ;
- contenu relativement simple à récupérer.

**Problème principal :** contenu hétérogène en longueur, qualité et structure.

Il vaut mieux éviter d’envoyer directement les pages brutes dans le vector store.

Passer par une extraction normalisée :

```json
{
  "opening": "",
  "variation": "",
  "side": "",
  "move_explanations": [],
  "white_plans": [],
  "black_plans": [],
  "pawn_breaks": [],
  "key_squares": [],
  "piece_placements": [],
  "common_mistakes": [],
  "strategic_tradeoffs": []
}
```

Puis reconstruire des unités de prose homogènes.

### 2.3 Project Gutenberg

Intéressant pour les ouvrages d’échecs du domaine public.

Exemples utiles :

- *Chess Fundamentals* — José Raúl Capablanca ;
- *Chess Strategy* — Edward Lasker ;
- autres ouvrages classiques sur les principes du jeu.

Le plus intéressant n’est pas forcément la théorie d’ouverture exacte, parfois datée, mais la prose sur :

- développement ;
- centre ;
- activité des pièces ;
- structure de pions ;
- colonnes ouvertes ;
- cases faibles ;
- bons et mauvais fous ;
- échange de pièces ;
- initiative ;
- plans stratégiques.

### 2.4 Wikisource

Peut compléter Gutenberg avec :

- livres anciens ;
- chapitres dédiés aux ouvertures ;
- commentaires move-by-move ;
- prose stratégique.

À utiliser surtout pour les principes généraux, motifs récurrents et idées derrière les coups.

### 2.5 Corpus propriétaire WikiChess

À terme, le meilleur corpus peut devenir celui généré et validé par WikiChess.

À partir de :

- Stockfish ;
- statistiques Lichess ;
- structure de pions ;
- classification d’ouverture ;
- sources textuelles ;
- commentaires vérifiés ;

WikiChess peut produire ses propres unités pédagogiques.

Exemple :

> Dans cette structure, les Noirs cherchent généralement à jouer ...c5 afin d’attaquer la base de la chaîne de pions blanche en d4. Le coup prépare souvent une pression sur le centre tout en créant du contre-jeu sur l’aile dame.

Ces documents peuvent ensuite être validés, versionnés, associés à leur provenance et réutilisés dans le vector store.

---

## 3. Ce qui ne doit pas être confié au vector store

Le vector store ne doit pas être considéré comme une source d’autorité pour savoir quel coup est objectivement correct.

Éviter autant que possible les assertions du type :

> Le meilleur coup est ...c5.

Préférer :

> L’idée stratégique de ...c5 est d’attaquer la base de la chaîne de pions.

### Répartition des responsabilités

**Stockfish**

- validité tactique ;
- évaluation ;
- coups candidats ;
- lignes concrètes.

**Lichess**

- coups réellement joués ;
- fréquence ;
- fréquence par Elo ;
- résultats ;
- préférences humaines.

**RAG**

- pourquoi ce coup ;
- quel plan ;
- quel concept ;
- quelle structure ;
- quelles erreurs éviter ;
- comment expliquer la position.

**LangGraph**

- orchestration ;
- choix de stratégie ;
- combinaison des preuves ;
- décision sur le besoin ou non de retrieval.

---

## 4. Architecture générale

```text
                  POSITION UTILISATEUR
                         │
          ┌──────────────┼───────────────┐
          │              │               │
          ▼              ▼               ▼
       Lichess        Stockfish      Player profile
          │              │               │
          └──────────────┼───────────────┘
                         │
                 Conversation / question
                         │
                         ▼
                LANGGRAPH ORCHESTRATOR
                         │
                         ▼
                  Retrieval Planner
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
        ▼                ▼                 ▼
 Exact metadata     Semantic RAG     Structure search
        │                │                 │
        └────────────────┼─────────────────┘
                         │
                         ▼
                     Reranker
                         │
                         ▼
               Evidence aggregation
                         │
                         ▼
                  Coach generator
                         │
                         ▼
                 Consistency check
                         │
                         ▼
                    RESPONSE
```

---

## 5. Pourquoi LangGraph devient un système agentique

Un RAG classique ressemble à :

```text
question
   ↓
embedding
   ↓
top-k
   ↓
LLM
```

Dans WikiChess, l’orchestrateur peut choisir dynamiquement :

- s’il faut faire du retrieval ;
- quel type de retrieval utiliser ;
- quelles métadonnées filtrer ;
- quelles requêtes générer ;
- s’il faut lancer plusieurs recherches ;
- si le contexte disponible suffit déjà ;
- si un deuxième retrieval est nécessaire.

Le système devient :

```text
contexte
   ↓
raisonnement
   ↓
choix d’une stratégie
   ↓
appel d’un outil
   ↓
observation du résultat
   ↓
nouvelle décision éventuelle
   ↓
réponse
```

C’est une architecture agentique, mais contrôlée.

L’agent choisit parmi des outils prédéfinis ; il ne construit pas librement toute la logique de récupération.

---

## 6. Les stratégies de retrieval

### A. Exact metadata retrieval

Pour les demandes très précises.

Exemple :

> Pourquoi 6.Be3 dans cette Najdorf ?

Filtres :

```text
opening_family = Sicilian Defense
variation = Najdorf
side = white
move = Be3
```

### B. Metadata + semantic search

Probablement le mode par défaut.

Exemple :

> Pourquoi ...c5 ici ?

Filtres :

```text
opening_family = French Defense
side = black
```

Recherche sémantique :

```text
strategic purpose of c5
attack the base of the pawn chain
pressure on d4
```

### C. Semantic only

Pour les questions générales :

> Qu’est-ce qu’un mauvais fou ?

> Pourquoi faut-il attaquer la base d’une chaîne de pions ?

Ici, l’ouverture exacte importe peu.

### D. Structure-first retrieval

Très important aux échecs.

Deux ouvertures différentes peuvent mener à la même structure de pions.

Exemples :

- Carlsbad ;
- Isolated Queen Pawn ;
- Hanging Pawns ;
- Maroczy Bind ;
- Hedgehog ;
- centre fermé ;
- chaîne française.

Exemple :

```text
structure = carlsbad
side = white
concept = minority_attack
```

### E. Candidate move retrieval

Pour les demandes du type :

> Que jouer ici ?

Stockfish donne plusieurs candidats, Lichess fournit fréquence et résultats, puis le retrieval récupère pour chaque coup :

```text
why c5
plan after c5
risks of c5
```

Le coach peut ensuite comparer les options de manière pédagogique.

### F. No retrieval

Le système doit aussi pouvoir décider de ne rien chercher.

Exemple :

> Quelle est l’évaluation Stockfish ?

Si l’information est déjà disponible dans le state, le retrieval est inutile.

---

## 7. Retrieval Planner

Le Retrieval Planner est le cœur décisionnel.

Entrées :

```json
{
  "position": {},
  "opening": {},
  "lichess": {},
  "stockfish": {},
  "player": {},
  "conversation": {},
  "user_question": ""
}
```

Sortie structurée :

```json
{
  "strategy": "metadata_semantic",
  "queries": [
    "strategic purpose of c5",
    "attacking the base of the pawn chain"
  ],
  "filters": {
    "opening_family": ["French Defense"],
    "side": "black",
    "structure": ["closed_center"]
  },
  "boost": {
    "move:c5": 1.5,
    "concept:pawn_break": 1.4
  },
  "top_k": 12,
  "rerank_k": 4
}
```

Le LLM choisit la stratégie ; le moteur de retrieval reste déterministe.

---

## 8. Prise en compte de la question utilisateur

### Question précise

> Pourquoi ...c5 ?

→ candidate-move ou metadata retrieval.

### Question générale

> Quel est le plan ?

→ structure-first + semantic.

### Question conceptuelle

> C’est quoi une case faible ?

→ semantic only.

### Absence de question précise

Le coach peut devenir proactif et construire lui-même les requêtes pertinentes.

---

## 9. Cas sans question précise

Exemple :

Stockfish :

```text
c5  +0.18
Nc6 +0.23
f6  +0.31
```

Lichess :

```text
c5 45 %
Nc6 15 %
f6 17 %
```

Le planner peut générer :

```text
why c5 is thematic here
```

```text
typical plans for black in this pawn structure
```

```text
common mistakes for black in this position
```

On obtient alors du multi-query retrieval.

---

## 10. Rôle du niveau du joueur

Le niveau du joueur ne doit pas filtrer trop agressivement la connaissance.

Une idée stratégique vraie reste vraie à 1200 ou 2200 Elo.

Le niveau doit surtout agir sur la génération finale.

### Débutant

- explication simple ;
- un plan principal ;
- peu de variantes ;
- concepts concrets.

### Intermédiaire

- alternatives ;
- structures ;
- raisons positionnelles ;
- erreurs typiques.

### Avancé

- nuances ;
- transpositions ;
- compromis ;
- lignes concrètes ;
- comparaison de plusieurs coups proches.

Une metadata `difficulty` peut exister comme facteur de boost, mais pas nécessairement comme filtre strict.

---

## 11. Hybrid retrieval

Le ranking ne devrait pas être fondé uniquement sur la similarité vectorielle.

Exemple de score composite :

```text
final_score =
    semantic_similarity
  + opening_match
  + structure_match
  + move_match
  + source_quality
  + difficulty_match
```

Exemple de pondération :

```text
0.40 semantic similarity
0.20 opening match
0.15 structure match
0.10 move match
0.10 source quality
0.05 difficulty match
```

Ces poids peuvent varier selon l’intention.

---

## 12. Métadonnées recommandées pour les chunks

```json
{
  "opening_family": "French Defense",
  "variation": "Advance Variation",
  "side": "black",
  "concepts": [
    "pawn_chain",
    "pawn_break",
    "queenside_play"
  ],
  "moves": [
    "c5"
  ],
  "structures": [
    "closed_center",
    "french_chain"
  ],
  "content_type": "strategic_explanation",
  "difficulty": "intermediate",
  "source": "chess.stackexchange.com",
  "source_quality": 0.87,
  "license": "CC-BY-SA",
  "prose": "..."
}
```

Champs additionnels possibles :

```text
fen_candidates
eco
phase
key_squares
pawn_breaks
piece_placements
common_mistakes
related_positions
```

---

## 13. Reranking

Le vector store peut retourner 10 à 20 documents.

Un reranker sélectionne ensuite les 3 à 5 meilleurs.

```text
retrieve 15
      ↓
rerank
      ↓
keep 4
```

Le reranking peut prendre en compte :

- correspondance avec le coup candidat ;
- structure ;
- ouverture ;
- qualité de la source ;
- pertinence pour la question ;
- redondance.

Il faut éviter de fournir cinq chunks qui disent exactement la même chose.

---

## 14. Evidence Aggregator

Avant la génération finale, un nœud regroupe les informations.

```json
{
  "candidate_move": "c5",
  "engine": {
    "evaluation": 0.18,
    "rank": 1
  },
  "lichess": {
    "frequency": 0.45,
    "frequency_at_player_level": 0.51
  },
  "rag": {
    "strategic_idea": "attack d4",
    "pawn_break": true,
    "typical_plan": "queenside pressure"
  }
}
```

Le Coach Generator reçoit ainsi des preuves déjà structurées.

---

## 15. Coach Generator

Le Coach Generator transforme les preuves en explication.

Il reçoit :

- la position ;
- Stockfish ;
- Lichess ;
- connaissances RAG ;
- niveau du joueur ;
- historique de conversation.

Exemple :

> ...c5 est ici le coup le plus naturel. Il attaque immédiatement la base de la chaîne blanche en d4. C’est une idée typique de la Française : les Blancs gagnent de l’espace avec e5, tandis que les Noirs cherchent à exercer une pression sur d4. À ton niveau, le plus important est de retenir le plan plutôt que la séquence exacte : ...c5, pression sur d4, puis développement des pièces autour de cette faiblesse.

---

## 16. Consistency Checker

Dernier nœud avant réponse.

Il peut vérifier :

- le coup mentionné existe-t-il dans la position ?
- le côté au trait est-il correct ?
- la prose contredit-elle Stockfish ?
- les statistiques correspondent-elles au bon niveau ?
- une ligne tactique présentée est-elle réellement valide ?
- une information récupérée est-elle hors contexte ?

Exemple :

Le RAG dit :

> Le plan typique est ...c5.

Mais Stockfish dit :

```text
...c5 = -1.5
...Nd7 = +0.1
```

La réponse correcte devient :

> ...c5 est normalement la rupture thématique de cette structure, mais dans cette position précise elle est prématurée. Stockfish préfère d’abord ...Nd7 afin de préparer la rupture dans de meilleures conditions.

---

## 17. Architecture LangGraph recommandée

```text
START
  │
  ▼
load_position_context
  │
  ├─ position
  ├─ opening
  ├─ history
  └─ side_to_move
  │
  ▼
get_lichess_context
  │
  ▼
get_stockfish_context
  │
  ▼
load_player_profile
  │
  ▼
analyze_user_intent
  │
  ▼
retrieval_planner
  │
  ├── no_retrieval
  │
  ├── exact_metadata_search
  │
  ├── metadata_semantic_search
  │
  ├── semantic_search
  │
  ├── structure_search
  │
  └── candidate_move_search
  │
  ▼
retrieval_execution
  │
  ▼
reranker
  │
  ▼
evidence_aggregator
  │
  ▼
coach_generator
  │
  ▼
consistency_checker
  │
  ├── valid → RESPONSE
  │
  └── issue → correction → RESPONSE
```

---

## 18. Pourquoi éviter plusieurs agents

Éviter une architecture du type :

```text
Stockfish Agent
Lichess Agent
Opening Agent
RAG Agent
Strategy Agent
Coach Agent
Verifier Agent
```

Elle serait probablement trop complexe.

Préférer :

```text
1 orchestrateur LangGraph
+
5 stratégies de retrieval
+
outils Stockfish/Lichess
+
reranker
+
coach
+
validator
```

Cela reste observable, testable, moins coûteux et beaucoup plus simple à déboguer.

---

## 19. Exemple complet

Question :

> Pourquoi Stockfish préfère ...f6 alors que tout le monde joue ...c5 ?

State :

```text
Position

Stockfish:
  ...f6 +0.10
  ...c5 +0.18

Lichess 1500:
  ...c5 54 %
  ...f6 11 %

Player Elo:
  1450
```

### Étape 1 — Intent

```text
compare_candidate_moves
```

### Étape 2 — Retrieval Planner

Choisit :

```text
candidate_move_search
```

pour :

```text
...c5
...f6
```

### Étape 3 — Retrieval

Cherche :

```text
strategic purpose of c5
strategic purpose of f6
pawn-chain breaks in French structures
```

### Étape 4 — Structure retrieval

Si nécessaire :

```text
structure_search(
  french_chain,
  side=black
)
```

### Étape 5 — Evidence

Le système dispose alors de :

- préférence Stockfish ;
- comportement humain Lichess ;
- plans de ...c5 ;
- plans de ...f6 ;
- explication de la structure.

### Étape 6 — Coach

Réponse possible :

> ...c5 est le plan le plus courant parce qu’il attaque directement la base de la chaîne blanche en d4 et s’intègre naturellement au plan positionnel de la Française. ...f6 vise plutôt le sommet de la chaîne en e5 et crée immédiatement davantage de tension. Dans cette position précise, Stockfish considère que le timing de ...f6 est favorable, alors que les joueurs de ton niveau choisissent beaucoup plus souvent le plan standard ...c5.

---

## 20. Vision finale

```text
               STRUCTURED CHESS TRUTH
           Stockfish + Lichess + position
                       │
                       ▼
                LangGraph Planner
                       │
                       ▼
              CONTEXTUAL RETRIEVAL
                       │
                       ▼
                PEDAGOGICAL PROSE
                       │
                       ▼
                   COACH LLM
                       │
                       ▼
             PERSONALISED EXPLANATION
```

La séparation fondamentale est :

```text
Stockfish → validité échiquéenne
Lichess   → comportement humain
RAG       → compréhension
LangGraph → décision et orchestration
LLM       → pédagogie
```

---

## 21. Priorités d’implémentation

1. Continuer à enrichir la prose.
2. Normaliser Wikibooks.
3. Ingérer Chess Stack Exchange.
4. Ajouter des métadonnées riches aux chunks.
5. Mettre en place metadata + semantic retrieval.
6. Ajouter structure-first retrieval.
7. Ajouter candidate-move retrieval.
8. Créer le Retrieval Planner LangGraph.
9. Ajouter un reranker.
10. Construire l’Evidence Aggregator.
11. Ajouter le Coach Generator.
12. Terminer par le Consistency Checker.

### MVP agentique conseillé

```text
LangGraph Router
    ↓
3 strategies:
- metadata semantic
- semantic only
- candidate moves
    ↓
reranking
    ↓
coach
```

Les autres stratégies peuvent être ajoutées progressivement en fonction des erreurs observées en production.
