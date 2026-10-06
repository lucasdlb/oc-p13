# Milvus

Milvus contient la prose pedagogique vectorisee. La collection runtime est schema 4, dimension
1024, metrique COSINE, index HNSW (`M=16`, `efConstruction=200`, `search_ef=64`) et granularite
`section` par defaut.

## Champs Runtime

Le contrat est porte par `KnowledgeChunk` et `MilvusStore`. Chaque ligne correspond a un chunk de
prose pedagogique et a son vecteur.

| Champ | Type Milvus | Nullable | Role |
| --- | --- | --- | --- |
| `id` | `VARCHAR(64)` | non | Identifiant stable du chunk et cle primaire |
| `vector` | `FLOAT_VECTOR(1024)` | non | Embedding du champ `text` |
| `text` | `VARCHAR(max_text_length)` | non | Texte pedagogique vectorise |
| `source` | `VARCHAR(128)` | non | Source documentaire, par exemple Wikibooks |
| `source_url` | `VARCHAR(512)` | oui | URL de la source |
| `license_or_terms` | `VARCHAR(128)` | oui | Licence ou conditions d'utilisation |
| `page_id` | `VARCHAR(512)` | non | Identifiant `<source>::<page_title>` |
| `canonical_title` | `VARCHAR(512)` | non | Titre canonique de la page |
| `opening_name` | `VARCHAR(256)` | oui | Nom de l'ouverture associee |
| `eco_code` | `VARCHAR(16)` | oui | Code ECO associe |
| `opening_node_id` | `VARCHAR(64)` | oui | Noeud `OpeningTree` associe |
| `line_pgn` | `VARCHAR(512)` | oui | Ligne PGN associee au noeud |
| `section_title` | `VARCHAR(256)` | oui | Titre de la section source |
| `intent` | `VARCHAR(64)` | non | Intention documentaire, par exemple `plan`, `history` ou `misc` |
| `side` | `VARCHAR(16)` | oui | Camp concerne quand il est connu |
| `is_history` | `BOOL` | non | Indique une section historique |
| `is_misc` | `BOOL` | non | Indique une section diverse |
| `section_index` | `INT64` | oui | Position de la section dans la page |
| `part_index` | `INT64` | non | Position du chunk dans la section |
| `created_at` | `VARCHAR(40)` | non | Date de creation du chunk |

`page_id = <source>::<page_title>`. `section_index` et `part_index` permettent de reconstruire une
page. Les limites `VARCHAR` sont controlees en octets UTF-8.

## Champ Embedde

Le seul champ embedde est `text`. Le provider d'embeddings recoit le texte pedagogique de chaque
chunk et produit un vecteur de dimension 1024, stocke dans `vector`.

Les autres champs sont des metadonnees. Ils servent a filtrer les resultats, a identifier leur
origine ou a reconstruire la page dans son ordre d'origine; ils ne sont pas ajoutes au texte avant
la generation de l'embedding.

- Modifier `text` change l'identite du chunk et necessite un nouvel embedding.
- Modifier une metadata permet de reutiliser le vecteur si le stockage reste compatible.
- `page_id`, `section_index` et `part_index` servent a reconstruire une page dans l'ordre.
- `opening_node_id`, `eco_code`, `source`, `page_id` et `intent` servent au filtrage du retrieval.

## Index Et Recherche

Milvus combine deux etapes differentes:

1. La recherche vectorielle compare le vecteur de la question aux vecteurs `vector` des chunks.
   L'index HNSW permet de trouver rapidement les vecteurs proches sans comparer chaque ligne.
2. Les filtres metadata reduisent les candidats selon l'ouverture, la source, la page ou l'intention
   documentaire. Ils ne changent pas le vecteur et ne remplacent pas la similarite semantique.

### Index Metadata

Les champs suivants ont un index `INVERTED`:

| Champ | Effet de l'index | Utilite dans le retrieval |
| --- | --- | --- |
| `source` | Retrouve rapidement les chunks d'une source donnee | Limiter la recherche a Wikibooks ou a une autre source autorisee |
| `eco_code` | Retrouve rapidement les chunks associes a un code ECO | Restreindre la prose a l'ouverture identifiee |
| `opening_name` | Retrouve rapidement les chunks portant un nom d'ouverture | Filtrer par ouverture quand le nom est connu |
| `opening_node_id` | Retrouve rapidement les chunks lies a un noeud de l'arbre | Prioriser la prose du noeud courant et ses suites directes |
| `page_id` | Retrouve rapidement tous les chunks d'une page | Reconstruire une page ou limiter le contexte a une page precise |
| `intent` | Retrouve rapidement les chunks d'une intention documentaire | Inclure ou exclure `plan`, `history` ou `misc` selon la question |

Un index `INVERTED` est un index de valeurs pour les champs metadata. Il sert aux filtres comme
`source == "wikibooks"` ou `opening_node_id == "C60"`; il n'ordonne pas les chunks par pertinence
et ne produit pas d'embedding.

### Index Vectoriel

| Element | Valeur actuelle | Effet |
| --- | --- | --- |
| Schema | `4` | Version du contrat de stockage; une incompatibilite impose une nouvelle collection ou un reindex |
| Dimension | `1024` | Nombre de valeurs dans chaque embedding; doit correspondre au modele utilise |
| Metrique | `COSINE` | Compare l'orientation des vecteurs pour mesurer leur proximite semantique |
| Index | `HNSW` | Construit un graphe de voisins pour accelerer la recherche des vecteurs proches |
| `M` | `16` | Nombre maximal de connexions conservees par noeud; plus haut peut ameliorer le rappel mais coute plus de memoire |
| `efConstruction` | `200` | Effort utilise lors de la construction de l'index; plus haut peut ameliorer la qualite du graphe et ralentir l'ingestion |
| `search_ef` | `64` par defaut | Effort de recherche; le backend utilise `max(search_ef, k)` pour chercher au moins `k` candidats |
| Consistency | `Strong` | Garantit que les recherches voient les ecritures confirmees |
| Dynamic fields | desactives | Refuse les champs non declares et maintient un schema explicite |

Le retrieval applique d'abord les filtres compatibles avec la question, puis classe les candidats
par score COSINE. Les filtres `eco_code` et `MilvusMetadataFilter` sont construits par le backend;
les valeurs suspectes sont rejetees au lieu d'etre injectees dans l'expression Milvus.

## Compatibilite

Chaque collection porte un manifeste contenant schema, dimension, metrique, index et signature du
modele. Un changement de schema, modele, digest, dimension, metrique, cleaner, chunking ou texte
produit une nouvelle collection ou un nouveau snapshot. L'ancienne collection est conservee jusqu'a
validation de la nouvelle.

Milvus Lite sert le developpement, les tests et le harness. Milvus Standalone sert la demo via
Docker Compose. `MILVUS_URI` vient de l'environnement.

## Retrieval

Le retrieval est relationnel par rapport au noeud `OpeningTree` courant:

- prose du noeud courant en priorite;
- enfants directs uniquement comme suites conditionnelles;
- descendants profonds exclus ou penalises par defaut;
- sections `history` et `misc` exclues ou penalisees sauf intention explicite.

Milvus ne contient ni les lignes canoniques `chess-openings`, ni les caches, ni les reponses coach.
Les metriques sont dans [`../RAG-EVALUATION.md`](../RAG-EVALUATION.md) et les procedures dans
[`../runbooks/RAG.md`](../runbooks/RAG.md).
