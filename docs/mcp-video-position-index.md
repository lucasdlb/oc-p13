# Note de conception : système MCP de recherche vidéo par position

**Statut :** étude de conception, non implémentée
**Périmètre :** ressources vidéo pédagogiques liées à une position d'échecs
**Produit concerné :** POC Agent d'ouvertures FFE

## 1. Résumé exécutif

La recherche YouTube par nom d'ouverture constitue un premier fallback utile,
mais elle ne garantit pas que la vidéo explique la position actuellement affichée.
Une vidéo de 45 minutes sur la Sicilienne peut par exemple être proposée alors
que le joueur cherche uniquement à comprendre un échange ou un coup précis.

Le système étudié ici ajoute un index spécialisé capable de relier une position
d'échecs à un ou plusieurs passages vidéo. Les vidéos sont découvertes via
l'API YouTube Data v3, puis analysées hors ligne : extraction d'images,
détection de l'échiquier et conversion en FEN. Le résultat est exposé par un
serveur MCP afin que le backend et LangGraph puissent interroger cette capacité
comme un outil borné.

Cette architecture est faisable pour un catalogue réduit de vidéos validées.
Elle n'est pas nécessaire au parcours minimal du POC actuel et ne doit pas
remplacer la recherche YouTube classique tant que la qualité de l'indexation
n'a pas été mesurée.

## 2. Objectifs et périmètre

### Objectifs

- proposer une ressource vidéo associée à la position courante plutôt qu'à la
  seule famille d'ouverture ;
- fournir un lien YouTube avec un timestamp pertinent ;
- conserver la provenance, le niveau de confiance et le type de correspondance ;
- exposer la recherche par une interface MCP indépendante du backend métier ;
- permettre à LangGraph de sélectionner automatiquement la ressource vidéo ;
- conserver un fallback explicite vers une recherche YouTube textuelle.

### Hors périmètre initial

- télécharger ou réhéberger les vidéos YouTube ;
- indexer automatiquement l'ensemble de YouTube ;
- garantir une compréhension parfaite de tous les échiquiers filmés ;
- générer un clip vidéo propriétaire ;
- utiliser la vidéo comme source de vérité pour la légalité d'un coup ;
- remplacer Stockfish, Lichess ou le corpus pédagogique documentaire.

La légalité des coups, l'identification de l'ouverture et les faits de position
restent détenus par les services déterministes du backend.

## 3. Bénéfices attendus

### Bénéfices pédagogiques

- **Pertinence locale :** la vidéo est reliée à la position courante et non
  uniquement au nom de l'ouverture.
- **Réduction de la charge cognitive :** l'élève arrive directement au passage
  utile au lieu de chercher manuellement dans une vidéo longue.
- **Continuité du parcours :** une ressource peut être proposée après chaque
  analyse, au même endroit que les statistiques et l'explication du coach.
- **Progressivité :** le classement peut prendre en compte le niveau
  `debutant`, `intermediaire` ou `avance`.
- **Explication multimodale :** le coach peut associer son explication textuelle
  à une démonstration visuelle externe.

### Bénéfices techniques

- **Découplage :** le serveur MCP encapsule l'index vidéo et son évolution sans
  imposer cette logique aux services FastAPI ou au coach.
- **Réutilisation :** le même outil peut être utilisé par une interface web,
  un agent de démonstration ou un outil d'annotation.
- **Traçabilité :** chaque résultat peut inclure la FEN recherchée, le timestamp,
  le score, la source et la méthode de matching.
- **Réduction des appels live :** l'analyse coûteuse est réalisée à l'ingestion ;
  la recherche courante consulte ensuite un index local.
- **Évolutivité :** l'index peut accueillir ensuite la transcription, les
  chapitres, les thèmes tactiques ou plusieurs variantes d'une position.

## 4. Limites et risques

### Qualité de la reconnaissance

La conversion d'une image en FEN dépend fortement de la résolution, de la
perspective, de l'orientation de l'échiquier, des animations, des pièces
capturées, des incrustations et de la visibilité des cases. Une erreur sur une
seule pièce peut produire une FEN légalement plausible mais incorrecte.

Le système doit donc stocker un score de confiance et distinguer au minimum :

- `exact_fen` : position reconnue et validée ;
- `near_position` : position proche après normalisation ou distance contrôlée ;
- `opening_match` : correspondance par ouverture, sans preuve visuelle de la FEN ;
- `text_search_fallback` : recherche YouTube non indexée.

Une correspondance de faible confiance ne doit pas être présentée comme une
preuve que la vidéo explique exactement la position.

### Couverture limitée

Un index réduit ne couvrira qu'un nombre limité d'ouvertures et de chaînes. Une
absence de résultat ne signifie pas qu'aucune vidéo pertinente n'existe sur
YouTube ; elle signifie seulement que le catalogue indexé n'en contient pas.

### Coûts et latence

L'indexation est plus coûteuse que la recherche textuelle : extraction de frames,
inférence de vision, validation des FEN et stockage des annotations. Elle doit
être asynchrone et hors du chemin critique de l'analyse d'une position.

### Quotas et dépendance YouTube

L'API YouTube Data v3 est soumise à un quota quotidien par projet. La méthode
`search.list` est particulièrement coûteuse en unités de quota, tandis que les
résultats mis en cache évitent les recherches répétées. Les valeurs de quota
doivent être vérifiées dans la console Google du projet avant chiffrage final.

Le système doit limiter les recherches, utiliser le cache et ne jamais relancer
une indexation complète à chaque demande utilisateur.

### Conditions d'utilisation et droits

Le système ne doit pas télécharger, modifier ou redistribuer les vidéos sans
base juridique appropriée. Le périmètre recommandé est de conserver :

- l'identifiant et l'URL YouTube ;
- les métadonnées autorisées ;
- les timestamps ;
- les FEN et scores produits par le pipeline ;
- la date de collecte et la version de l'index.

L'affichage intégré doit respecter les possibilités d'embed et les conditions
de la plateforme. Un lien externe reste le fallback de référence.

## 5. Architecture technique cible

```mermaid
flowchart LR
    Y[YouTube Data API v3] --> D[Découverte des vidéos]
    D --> M[(MongoDB métadonnées)]
    D --> F[Extraction de frames]
    F --> V[Modèle vision board-to-FEN]
    V --> L[Validation FEN et score]
    L --> I[(Index positions vidéo)]

    P[Position courante FEN] --> B[Backend FastAPI]
    B --> G[LangGraph]
    G --> MCP[Serveur MCP vidéo]
    MCP --> I
    MCP --> M
    I --> R[Résultats: URL + timestamp + confiance]
    M --> R
    R --> G
    G --> B
    B --> UI[Frontend Angular]
```

### Composants

| Composant | Responsabilité | Nature |
| --- | --- | --- |
| Découverte YouTube | Rechercher les vidéos par ouverture et mots-clés | Appel externe |
| Extracteur de frames | Échantillonner les images d'une vidéo | Batch asynchrone |
| Modèle board-to-FEN | Détecter l'échiquier et produire une FEN | Vision |
| Validateur FEN | Vérifier la syntaxe et la cohérence minimale | Déterministe |
| Index positions vidéo | Associer FEN, vidéo, timestamp et confiance | MongoDB ou index dédié |
| Serveur MCP | Exposer la recherche comme outil borné | Service interne |
| Noeud LangGraph | Appeler MCP selon les résultats Explorer | Orchestration |
| Backend FastAPI | Contrat API, fallbacks et contrôle des sources | Application |
| Frontend Angular | Afficher lien, timestamp et statut | Interface |

### Flux d'ingestion

1. Le pipeline reçoit une ouverture, une liste de vidéos ou une requête YouTube.
2. Il récupère les métadonnées nécessaires sans réhéberger la vidéo.
3. Il extrait des frames à intervalle configurable, par exemple toutes les 5 à
   10 secondes.
4. Le modèle de vision identifie l'échiquier et produit éventuellement une FEN.
5. Le validateur rejette les sorties invalides et attribue un score de confiance.
6. Le pipeline regroupe les occurrences proches afin d'éviter des entrées
   redondantes pour la même séquence.
7. Il persiste les timestamps, FEN, métadonnées, version du modèle et statut de
   validation.

### Flux de recherche

1. Explorer identifie l'ouverture et fournit la FEN courante.
2. LangGraph appelle le service vidéo uniquement si la fonctionnalité est
   activée et si une position exploitable est disponible.
3. MCP recherche d'abord une FEN exacte, puis une position proche selon un seuil
   déterministe.
4. Si aucun résultat fiable n'est trouvé, le service renvoie un résultat vide
   explicite ou délègue au fallback de recherche textuelle.
5. Le frontend affiche le titre, la chaîne, le lien avec timestamp et le niveau
   de confiance. Il ne présente pas le résultat comme une recommandation
   certaine lorsque le matching est approximatif.

## 6. Interface MCP proposée

Le serveur MCP ne décide pas librement des sources critiques. Il expose des
outils spécialisés, avec des paramètres bornés et des résultats structurés.

### `search_video_by_fen`

Entrée :

```json
{
  "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/1b2P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
  "opening_name": "Ruy Lopez",
  "level": "debutant",
  "max_results": 3
}
```

Sortie :

```json
{
  "results": [
    {
      "title": "Ruy Lopez explained",
      "video_id": "abc123",
      "url": "https://www.youtube.com/watch?v=abc123&t=420s",
      "channel_title": "Chess Channel",
      "timestamp_seconds": 420,
      "matched_fen": "r1bqkbnr/pppp1ppp/2n5/4p3/1b2P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
      "confidence": 0.91,
      "match_type": "exact_fen",
      "source": "mcp-video-position-index"
    }
  ],
  "fallbacks_used": []
}
```

### `search_video_by_opening`

Cet outil sert de repli lorsque la FEN n'est pas indexée. Il effectue une
recherche contrôlée par ouverture, niveau et mots-clés, puis retourne des liens
YouTube sans prétendre qu'un timestamp correspond à la position exacte.

### Règles de sécurité et de contrôle

- `max_results` est plafonné côté serveur ;
- la requête ne peut pas demander une exploration illimitée ;
- les résultats sont filtrés sur leur type vidéo et leur identifiant ;
- les URLs sont reconstruites à partir de l'identifiant YouTube validé ;
- aucune donnée secrète ou clé API n'est exposée au modèle ou au frontend ;
- le serveur retourne les raisons de fallback et les scores de confiance.

## 7. Intégration LangGraph

Le noeud LangGraph reste mince et délègue au service MCP. Il ne contient ni
logique de vision, ni accès direct à YouTube, ni logique de persistance.

```text
Start
  -> normalize_position
  -> identify_opening
  -> fetch_lichess_stats
  -> retrieve_rag_context
  -> maybe_run_stockfish
  -> maybe_search_video_mcp
       |-- résultat fiable --> attach_video_resources
       |-- résultat vide ----> youtube_text_fallback
       |-- MCP indisponible -> visible fallback
  -> generate_coach_answer
  -> End
```

Le coach peut mentionner l'existence d'une ressource vidéo, mais il ne doit pas
inventer son contenu. Le titre, la chaîne, le timestamp et le score doivent
provenir du résultat validé.

## 8. Étude de faisabilité

### Faisabilité fonctionnelle

**Évaluation : faisable sous contrainte.** Un POC peut être réalisé sur un
catalogue fermé de 10 à 30 vidéos sélectionnées manuellement et sur quelques
ouvertures de démonstration. Cette approche permet de tester le parcours MCP
sans résoudre immédiatement l'indexation générale de YouTube.

### Faisabilité technique

| Niveau | Périmètre | Résultat attendu |
| --- | --- | --- |
| POC 1 | Métadonnées YouTube + recherche textuelle MCP | Architecture et contrat validés |
| POC 2 | Frames pré-calculées sur 10 vidéos | Premiers timestamps associés à des FEN |
| POC 3 | 30 vidéos, validation manuelle, scores | Démonstration crédible de recherche par position |
| V1 | Pipeline batch automatisé et monitoring | Catalogue maintenable |
| V2 | Matching approximatif, transcription, thèmes | Recherche multimodale avancée |

### Hypothèse de charge POC

Pour 30 vidéos de 20 minutes, avec une frame toutes les 10 secondes :

- 120 frames par vidéo ;
- environ 3 600 frames au total ;
- une seule analyse par frame, puis stockage des seules détections utiles ;
- recherche utilisateur servie par l'index, sans nouvelle analyse vidéo.

Le nombre de frames dépend fortement de l'intervalle, de la durée et de la
présence de chapitres. Une détection de changement de scène peut réduire le
volume, au prix d'une étape supplémentaire.

### Critères de réussite proposés

- au moins 80 % des positions annotées manuellement sont reconnues avec une FEN
  exploitable sur le jeu de vidéos POC ;
- au moins 70 % des trois premiers résultats sont jugés pertinents par un
  évaluateur humain ;
- un résultat exact contient un timestamp à moins de 10 secondes du passage
  pédagogique ciblé ;
- l'absence de résultat déclenche un fallback visible sans bloquer l'analyse ;
- aucune clé API, vidéo téléchargée ou affirmation non sourcée n'est exposée.

Ces seuils sont des objectifs de validation et non des performances garanties.

## 9. Estimation des coûts

Les montants ci-dessous sont des ordres de grandeur pour cadrer la décision,
pas un devis. Ils dépendent du fournisseur cloud, du modèle de vision, du volume
de vidéos et du quota YouTube effectivement disponible.

### Coûts du POC

| Poste | Hypothèse | Estimation |
| --- | --- | ---: |
| YouTube Data API | Projet Google existant, quota standard, recherches limitées | 0 EUR de licence, quota à surveiller |
| Stockage métadonnées | MongoDB local ou instance existante | 0 à 20 EUR/mois |
| Stockage frames temporaires | Quelques milliers à dizaines de milliers de frames | 0 à 20 EUR/mois |
| Calcul vision local | Machine de développement avec GPU/CPU disponible | 0 EUR de service, coût machine existant |
| Calcul vision cloud | Batch ponctuel si le local est insuffisant | 10 à 100 EUR pour expérimentation |
| Serveur MCP local | Processus Python conteneurisé | inclus dans l'infrastructure POC |
| Développement POC | Contrat, index réduit, tests et démonstration | 3 à 6 jours.homme |

### Coûts d'une première version maintenable

| Poste | Estimation indicative |
| --- | ---: |
| Pipeline ingestion, validation et reprise | 5 à 10 jours.homme |
| Serveur MCP et intégration LangGraph | 2 à 4 jours.homme |
| Frontend, timestamps et états de fallback | 1 à 3 jours.homme |
| Évaluation qualité et annotation | 3 à 7 jours.homme |
| Monitoring, cache et documentation | 2 à 4 jours.homme |
| Total indicatif | 13 à 28 jours.homme |

Pour un catalogue limité, un budget d'exploitation de **20 à 150 EUR par mois**
est plausible hors coût humain, selon l'hébergement et l'utilisation de GPU.
Une indexation fréquente ou un catalogue volumineux peut dépasser largement
ce montant.

### Quota YouTube

Le coût financier direct de l'API peut être nul dans le quota attribué au
projet, mais le quota est une contrainte opérationnelle. Les recherches doivent
être mises en cache, dédupliquées et exécutées en batch. Le chiffrage définitif
doit être fait à partir de la console Google du projet et du nombre réel de
requêtes `search.list` et `videos.list`.

## 10. Recommandation de trajectoire

### Pour la démonstration actuelle

Conserver la recherche YouTube textuelle et son fallback visible. Elle est plus
simple, immédiatement compréhensible et suffisante pour montrer l'intégration
vidéo dans le parcours d'ouverture.

### Pour le prototype MCP

Créer un catalogue fermé de vidéos et d'annotations validées manuellement.
Implémenter d'abord `search_video_by_fen` sur des FEN connues, sans chercher à
automatiser tout le pipeline vision. Cette version permet de démontrer le
contrat MCP, le timestamp et l'intégration LangGraph avec un risque limité.

### Pour une évolution produit

Automatiser progressivement l'ingestion, introduire les scores de confiance,
mesurer la pertinence sur un jeu de référence et ne rendre le matching
approximatif visible qu'après validation. Le fallback YouTube textuel doit rester
disponible tant que la couverture et la précision du catalogue ne sont pas
suffisantes.

## 11. Conclusion

Le système MCP d'indexation vidéo par position répond au principal défaut de la
recherche YouTube textuelle : elle ne sait pas localiser le passage utile dans
une vidéo par rapport à la position courante.

Le bénéfice pédagogique attendu est important, mais il dépend directement de
la qualité du pipeline board-to-FEN et de la sélection des vidéos. La solution
est donc pertinente comme évolution stratégique et comme démonstrateur sur un
catalogue réduit, mais disproportionnée pour une première intégration YouTube
générique.

La recommandation est de séparer clairement les deux niveaux :

- **solution immédiate :** recherche YouTube classique, cache et fallback ;
- **solution avancée :** serveur MCP, index FEN/timestamp et ressources vidéo
  validées par position.
