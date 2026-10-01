# Sessions MongoDB et politique de cache

Status: accepted

MongoDB endosse deux roles : persister les sessions de demonstration et cacher les reponses des services externes. MongoDB n'est jamais la source des noms d'ouvertures (Lichess Opening Explorer reste prioritaire, le seed local `opening_book.py` reste le fallback offline) ni la base vectorielle (Milvus reste le corpus pedagogique).

## Decisions

- Sessions creees paresseusement : aucune session n'est creee au demarrage de l'application ni au clic sur Reinitialiser. La session est creee au premier coup joue et analyse, puis chaque nouveau coup est ajoute (`POST /api/analyze-position` avec `session_id` optionnel cree et retourne la session). Une reinitialisation apres des coups joues laisse l'ancienne session rejouable via `GET /api/sessions/{id}` et la prochaine analyse cree une nouvelle session.
- Les coups et analyses sont embarques dans le document `sessions`. Le niveau pedagogique et la plage de rating vivent sur chaque analyse, pas sur la session.
- Cles de cache :
  - `lichess_cache` : variante + sequence de coups UCI normalisee + buckets de rating. TTL 24 h via index MongoDB `expireAfterSeconds`.
  - `stockfish_cache` : FEN normalisee + profondeur + version du binaire. Pas de TTL : l'evaluation est deterministe, la version dans la cle invalide naturellement les anciens resultats.
  - `videos_cache` : requete normalisee. TTL 7 jours.
- Seules les reponses reussies sont cachees : les fallbacks Lichess (seed) et les evaluations Stockfish `unavailable` ne sont jamais ecrits en cache.
- Degradation : une indisponibilite MongoDB n'empeche jamais une analyse. Les lectures echouent silencieusement vers un miss de cache, les ecrits sont ignorees, la session n'est pas persistee. La deconnexion est visible via `fallbacks_used` et l'absence de `session_id`.
- Comportement de navigation : jouer un nouveau coup apres un retour en arriere supprime la variation suivante (troncature de la ligne dans la session comme dans le timeline frontend). La navigation vers une position pas encore analysee declenche une analyse automatique ; une position deja analysee est restauree depuis le cache de position du frontend.
- Sequencement : le travail RAG/Milvus vient apres les phases sessions et caches. C'est un ecart assume avec l'ordre `docs/PLAN.md` (Milvus etape 6, YouTube etape 8), accepte pour livrer la valeur produit (navigation, sessions, caches) avant la brique vectorielle.

## Consequences

- L'URI MongoDB est une valeur specifique a l'environnement : elle vient de `MONGODB_URI` dans l'environnement ou `.env`, jamais de `config.toml` (un `mongodb.uri` dans `config.toml` est ignore au chargement, comme `lichess.token`).
- Les autres parametres MongoDB (base, timeouts, TTLs) vivent dans `config.toml` sous `[mongodb]` et sont valides par Pydantic.
- `pymongo` devient une dependance du backend.
- La reponse de `POST /api/analyze-position` gagne `session_id` et `cache` (statuts hit/miss/skipped) sans casser le contrat existant.
- Le fichier `TODO.md` a la racine est un document de travail temporaire non autoritaire : `docs/PLAN.md` et `docs/DATA.md` restent les sources de verite.
