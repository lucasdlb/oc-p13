# Donnees, sources et persistance

Ce document est la source de verite pour les donnees du POC : sources externes, roles de MongoDB et Milvus, caches, matching d'ouvertures et validation des licences.

## Principe de separation

MongoDB stocke les donnees structurees et les caches operationnels. Milvus stocke le texte pedagogique vectorise pour la recherche semantique. Le coach IA ne doit pas utiliser MongoDB comme corpus long principal et ne doit pas utiliser Milvus comme base de verite structuree.

## MongoDB

MongoDB sert a retrouver vite une ouverture, conserver les sessions et eviter les appels repetes aux APIs externes.

Collections cibles :

- `openings` : ouvertures structurees importees ou seedees.
- `sessions` : historique local d'une session de demonstration.
- `analysis_cache` : analyses recentes si utile pour stabiliser la demo.
- `lichess_cache` : statistiques Lichess mises en cache.
- `videos_cache` : resultats YouTube ou fallback associes a une recherche.
- `source_registry` : sources utilisees, statut de validation et conditions.

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

### Collection `lichess_cache`

Role : limiter les appels Lichess et stabiliser la demo.

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
pgn
fen_or_epd
chunk_title
created_at
```

Milvus peut contenir :

- chunks Wikibooks ou autre source pedagogique validee ;
- descriptions courtes generees seulement si leur origine est documentee ;
- passages utiles pour expliquer plans, idees et pieges d'une ouverture.

Milvus ne doit pas contenir :

- la source canonique du matching ;
- les caches Lichess ou YouTube ;
- des reponses coach considerees comme verite.

## Registre des sources

Chaque source utilisee doit etre documentee dans `source_registry` ou dans une note de recherche avant usage central.

| Source | Role | Statut initial | Notes |
| --- | --- | --- | --- |
| `lichess-org/chess-openings` | Matching local et seed MongoDB | A valider | Licence annoncee CC0, a confirmer au moment de l'ingestion |
| Lichess Opening Explorer | Stats live et coups populaires | A valider | Verifier conditions API et besoin de token |
| Wikibooks Chess Opening Theory | Corpus pedagogique RAG | A valider | Verifier licence et structure d'extraction |
| Wikichess / FICGS | Source optionnelle | A verifier | Mentionnee par le brief, mais HTML et conditions a challenger |
| YouTube Data API | Videos explicatives | A valider | Prevoir fallback lien de recherche |

## Politique de texte pedagogique

Le texte long relatif a une ouverture va dans Milvus. MongoDB peut contenir uniquement un resume court ou des idees principales si cela sert l'affichage rapide, avec source explicite.

Les reponses du coach IA peuvent etre stockees dans `sessions` comme historique, mais jamais comme source de verite pour une ouverture.
