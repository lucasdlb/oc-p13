# Donnees, sources et persistance

Ce document est la source de verite pour les donnees du POC : sources externes, roles de MongoDB et Milvus, caches, matching d'ouvertures et validation des licences.

Le detail champ par champ des APIs externes (inventaire complet Lichess Opening Explorer, Lichess Cloud Evaluation et Stockfish UCI, ce que le backend recupere, ce qui est ignore, et les opportunites associees) vit dans `docs/DATA-SCHEMAS.md`.

## Principe de separation

MongoDB stocke les donnees structurees et les caches operationnels. Milvus stocke le texte pedagogique vectorise pour la recherche semantique. Le coach IA ne doit pas utiliser MongoDB comme corpus long principal et ne doit pas utiliser Milvus comme base de verite structuree.

## MongoDB

MongoDB sert a retrouver vite une ouverture, conserver les sessions et eviter les appels repetes aux APIs externes.

Collections cibles :

- `openings` : ouvertures structurees importees ou seedees. Etat POC : le seed vit encore dans `backend/app/services/opening_book.py` comme fallback offline ; la migration vers MongoDB reste a faire.
- `sessions` : historique local d'une session de demonstration.
- `analysis_cache` : remplacee par l'embarquement des analyses dans `sessions` (ADR 0005) ; la collection n'est pas utilisee.
- `lichess_cache` : statistiques Lichess mises en cache (les reponses Masters partagent la collection avec un prefixe de cle dedie).
- `stockfish_cache` : evaluations Stockfish reussies, cles par FEN normalisee + profondeur + version du moteur.
- `videos_cache` : resultats YouTube ou fallback associes a une recherche. Reservee a l'integration YouTube API.
- `source_registry` : sources utilisees, statut de validation et conditions. A venir.

### Collection `sessions`

Role : conserver et rejouer une session de demonstration.

Etat POC actuel (ADR 0005) : la session est creee paresseusement au premier coup joue et analyse via `POST /api/analyze-position` (champ `session_id` optionnel, cree et retourne). Chaque nouveau coup est ajoute ; la navigation en arriere ou avant ne modifie jamais la session ; un nouveau coup joue apres un retour en arriere tronque la variation abandonnee. Les coups et analyses sont embarques dans le document, le niveau pedagogique vit sur chaque analyse. Si MongoDB est indisponible, l'analyse continue sans persistance et `fallbacks_used` contient `mongo_sessions_unavailable`.

### Collection `openings`

Role : matching local d'une ligne jouee vers une ouverture connue.

Exemple minimal :

```json
{
  "eco": "C60",
  "name": "Ruy Lopez",
  "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
  "uci": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
  "epd": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq -",
  "source": "lichess-org/chess-openings"
}
```

Le matching local doit chercher dans cet ordre :

1. Correspondance exacte sur la sequence UCI.
2. Correspondance exacte sur EPD si disponible.
3. Correspondance par prefixe UCI pour identifier la ligne la plus specifique encore connue.
4. Absence de match explicite, ce qui peut declencher Stockfish.

Quand Lichess Opening Explorer est disponible et renvoie une ouverture (`eco`, `name`), celle-ci est prioritaire sur le matching local pour l'ouverture affichee ; le seed local devient alors un fallback offline. Les coups populaires Lichess et leurs statistiques associees (`games`, `white`, `draws`, `black`, `average_rating`) enrichissent egalement `recommended_moves` avec la source `lichess-opening-explorer`.

`lichess-org/chess-openings` doit aussi etre exploite comme **arbre structurel d'ouvertures**, separe du corpus Milvus. Pour une position connue, le backend peut construire une fenetre locale autour du noeud courant : parent immediat, noeud courant, enfants directs, et petits-enfants uniquement pour du ranking interne. Les descendants plus profonds ne doivent pas etre donnes au coach par defaut. Les enfants directs representent des suites possibles depuis la position courante ; ils ne doivent jamais etre presentes comme deja joues tant que leur coup d'entree n'est pas dans la ligne.

Les recommandations pratiques utilisent une politique de confiance configurable dans `config.toml` :

- `recommendations.min_move_share` : part minimale d'un coup dans les parties de la position filtree, par defaut `0.001` soit `0.1%`.
- `recommendations.min_position_games` : nombre minimal de parties dans la position filtree, par defaut `100`.
- `recommendations.rating_presets` : raccourcis de plages Lichess pour `debutant`, `intermediaire`, `avance`.

Le frontend peut envoyer `rating_min` et `rating_max` pour surcharger le preset pedagogique. Les valeurs sont mappees sur les buckets supportes par Lichess Opening Explorer (`0`, `1000`, `1200`, `1400`, `1600`, `1800`, `2000`, `2200`, `2500`).

Masters Opening Explorer est interroge separement et alimente `masters_moves`. Ces coups ne sont pas melanges aux recommandations Lichess : ils servent a montrer la theorie/top games a part.

### Collection `lichess_cache`

Role : limiter les appels Lichess et stabiliser la demo.

Etat POC actuel (ADR 0005) : l'analyse consulte la collection avant d'appeler Lichess Opening Explorer. Sur hit, la reponse cachee est servie sans appel HTTP. Sur miss, l'analyse appelle `https://explorer.lichess.org` seulement si `lichess.enabled = true` dans `config.toml` et si `LICHESS_TOKEN` est present dans l'environnement ou `.env` ; seule une reponse reussie est mise en cache (jamais un fallback seed). Le token est un secret et ne doit pas etre stocke dans `config.toml` : tout `lichess.token` present dans `config.toml` est ignore au chargement des settings, seul `LICHESS_TOKEN` de l'environnement ou `.env` est accepte. La cle couvre la variante, la sequence de coups UCI normalisee et les buckets de rating ; les reponses Masters utilisent la meme collection avec un prefixe de cle dedie. TTL 24 h via index MongoDB `expireAfterSeconds`. En cas d'erreur HTTP, timeout, reponse invalide, acces non autorise ou statistiques vides, elle renvoie le seed local `seed-lichess-cache` et ajoute un fallback explicite dans `fallbacks_used`. Si MongoDB est indisponible, l'analyse appelle Lichess directement sans ecrire de cache : l'indisponibilite est visible via le champ `cache` de la reponse (`skipped`).

La collection `stockfish_cache` suit la meme logique (hit/miss, jamais de resultat `unavailable` en cache), sans TTL : la cle contient la version du moteur, donc un changement de binaire invalide naturellement les anciens resultats.

Exemple minimal :

```json
{
  "fen_or_epd": "...",
  "moves": [],
  "top_moves": [],
  "fetched_at": "2026-09-29T00:00:00Z",
  "source": "lichess-opening-explorer"
}
```

### Collection `videos_cache`

Role : conserver les resultats YouTube ou un fallback de recherche.

Exemple minimal :

```json
{
  "query": "Ruy Lopez chess opening beginner",
  "opening_name": "Ruy Lopez",
  "eco": "C60",
  "results": [],
  "fallback_url": "https://www.youtube.com/results?search_query=Ruy+Lopez+chess+opening+beginner",
  "fetched_at": "2026-09-29T00:00:00Z",
  "source": "youtube-api"
}
```

## Milvus

Milvus sert a retrouver du contexte pedagogique par similarite semantique. Les chunks doivent rester lies a leurs sources.

Collection cible : `chess_knowledge`.

Champs recommandes :

```text
id
vector
text
source
url
license_or_terms
opening_name
eco_code
pgn
fen_or_epd
chunk_title
page_id
section_index
part_index
created_at
```

`eco_code` est la cle de jointure entre les sources (Lichess, Wikibooks) et sert au filtrage metadata a la requete. `page_id = <source>::<page_title>` identifie la page source ; avec `section_index` et `part_index` il permet de reassembler la page a partir des sections retrouvees. Le modele d'embeddings, la dimension et la metrique sont fixes par la collection : les decisions sont capturees dans `docs/adr/0006-rag-milvus-and-embeddings.md`.

Etat POC (phase R, ADR 0006) : la collection est servie par `MilvusStore` (`backend/app/services/milvus.py`), version de schema 3, dimension 1024, metrique COSINE, index HNSW, `id = SHA256(source + text)` (upsert idempotent), index scalaires sur `source`, `eco_code`, `opening_name`, `page_id`. Chaque collection porte un **manifeste** de compatibilite de stockage (schema, dimension, metrique, index physique, signature d'embeddings) separe des parametres de retrieval : reutiliser une collection incompatible echoue et exige une nouvelle collection. Les collections schema 2 restent des sources de reutilisation explicites en lecture seule lorsqu'elles sont vectoriellement compatibles ; elles ne sont pas des cibles validees. Les limites `VARCHAR` sont validees en octets UTF-8. Milvus Lite (fichier local) pour le dev, les tests et le harness ; Milvus standalone dans `docker-compose.yml` pour la demo. Granularite de chunk par defaut : `section` (mesure refaite en prose seule, ADR 0006).

Le retrieval prose doit etre **relationnel par rapport au noeud d'ouverture courant**, pas un top-k plat sur tout l'arbre. Politique cible : recuperer d'abord la prose du noeud courant ; inclure de la prose des enfants directs seulement comme contexte conditionnel de suites possibles, avec budget separe, penalite de ranking et libelle explicite (`relation_to_position = child`, `entry_move`). Exemple : apres `1. e4 e5 2. Nf3 Nc6 3. Bb5`, la prose Ruy Lopez est contexte principal ; les chunks Berlin ou Morphy peuvent expliquer `...Nf6` ou `...a6` comme suites candidates, mais le coach doit dire "si les Noirs jouent ...Nf6" et non "la position est une Berlin". Les sections `history` ou `misc` doivent etre baissees ou exclues par defaut sauf question explicite.

Milvus peut contenir :

- chunks de prose pedagogique validee (Wikibooks pour l'instant) ;
- descriptions courtes generees seulement si leur origine est documentee ;
- passages utiles pour expliquer plans, idees et pieges d'une ouverture.

Milvus ne doit pas contenir :

- la source canonique du matching (donc pas les lignes `chess-openings`) ;
- les caches Lichess ou YouTube ;
- des reponses coach considerees comme verite.

## Registre des sources

Chaque source utilisee doit etre documentee dans `source_registry` ou dans une note de recherche avant usage central.

| Source | Role | Statut initial | Notes |
| --- | --- | --- | --- |
| `demo-opening-seed` | Seed local minimal pour les scenarios MVP | Valide pour POC local | Donnees limitees codees dans le depot avant ingestion MongoDB |
| `lichess-org/chess-openings` | Matching local, seed MongoDB, arbre d'ouvertures et join/filtre `eco_code` (structure) | Valide | CC0-1.0 ; cinq TSV `a`-`e` (`eco`/`name`/`pgn`), noms en anglais. **Non ingestee dans Milvus** (ADR 0006 revise) : c'est une donnee structuree, pas de la prose. |
| Lichess Opening Explorer | Stats live, coups populaires et identification d'ouverture prioritaire | A valider | OpenAPI indique OAuth2 sur `explorer.lichess.org` ; utiliser `LICHESS_TOKEN` et fallback seed |
| Lichess Cloud Evaluation | Evaluation profonde pre-calculee (voie rapide / fallback Stockfish local) | Reporte v2 | Candidat non implemente ; `GET lichess.org/api/cloud-eval` sans auth, environ 320 M positions, score du point de vue des Blancs ; base d'evaluations CC0. Voir `docs/DATA-SCHEMAS.md` et ADR 0006. |
| Wikibooks Chess Opening Theory | Corpus pedagogique RAG (prose) | A verifier | Licence CC BY-SA (attribution + partage a l'identique), contenu en anglais. 13 pages curees ingerees en phase R via l'API MediaWiki. `WikibooksAdapter` conserve la prose structuree et exclut templates, tables de theorie, references et navigation ; une page sale ou vide est rejetee. Attribution visible requise avant toute distribution ; voir ADR 0006. |
| Wikichess / FICGS | Source optionnelle | A verifier | Mentionnee par le brief, mais HTML et conditions a challenger |
| YouTube Data API | Videos explicatives | A valider | Prevoir fallback lien de recherche |

## Politique de texte pedagogique

Le texte long relatif a une ouverture va dans Milvus. MongoDB peut contenir uniquement un resume court ou des idees principales si cela sert l'affichage rapide, avec source explicite.

Les reponses du coach IA peuvent etre stockees dans `sessions` comme historique, mais jamais comme source de verite pour une ouverture.
