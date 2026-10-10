# MongoDB

MongoDB persiste les sessions et les runs de demonstration, et cache les reponses externes. Il ne
remplace ni `OpeningTree` pour la structure des ouvertures ni Milvus pour la prose pedagogique.

## Collections

| Collection | Role | Etat |
| --- | --- | --- |
| `sessions` | historique rejouable d'une demonstration | utilisee |
| `analysis_runs` | facts Explorer et resultats progressifs par famille | utilisee |
| `openings` | matching runtime des ouvertures structurees | cible; seed local actuel |
| `lichess_cache` | Explorer et Masters, avec prefixe de cle | utilisee |
| `stockfish_cache` | evaluations reussies | utilisee |
| `videos_cache` | resultats YouTube enrichis par requete normalisee | utilisee |
| `source_registry` | registre persistant des sources | a venir |

## Sessions

Une session est creee paresseusement au premier coup analyse. Les coups et analyses sont embarques;
le niveau pedagogique vit sur chaque analyse. Un nouveau coup apres retour en arriere tronque la
variation abandonnee. Si MongoDB est indisponible, l'analyse continue sans persistance et expose
`mongo_sessions_unavailable`.

## Analysis Runs

`analysis_runs` stocke une analyse progressive: Explorer (incluant les ressources YouTube), puis
Stockfish, RAG et coach dans des mises a jour atomiques par famille. Les endpoints sont idempotents et relisent un resultat deja
`generated`, `fallback` ou `skipped`.

## Caches

- `lichess_cache`: variante, sequence UCI normalisee et buckets de rating; TTL 24 h.
- `stockfish_cache`: FEN normalisee, profondeur et version moteur; pas de TTL.
- `videos_cache`: requete normalisee; TTL 7 jours.
- Seules les reponses reussies sont cachees. Les fallbacks seed et evaluations `unavailable` ne le
  sont jamais.

La politique de cache et de degradation est decidee dans
`docs/adr/0005-mongodb-sessions-and-cache-policy.md`.
