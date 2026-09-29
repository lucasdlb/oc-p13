# Sources de donnees et politique de validation

Status: accepted

Le projet separe les roles des sources : `lichess-org/chess-openings` pour le matching local, Lichess Opening Explorer pour les statistiques live, Wikibooks ou une source pedagogique validee pour le contexte documentaire, et Wikichess seulement comme source optionnelle a verifier. Toute source doit etre documentee avec son URL, son role, sa licence ou ses conditions d'utilisation, son statut de validation et une justification courte avant d'etre utilisee comme dependance centrale de demonstration.

## Consequences

- Les agents peuvent rechercher de meilleures sources pedagogiques, mais doivent documenter leur statut.
- Une source non validee peut servir a explorer, pas a fonder la demo client.
- Le coach IA doit distinguer les faits sources des formulations pedagogiques.
