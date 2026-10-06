# Evidence pack et verificateur de claims

Status: proposed (2026-10-06; not yet implemented)

Cette decision renforce la frontiere deterministe du coach. Elle transforme le contexte multi-source
en preuves identifiables et verifie les affirmations produites avant leur diffusion. Elle complete
les ADR 0007, 0008, 0009 et 0010 sans rendre le coach agentique.

## Contexte

Le pipeline actuel produit deja un `CoachContext` source : prose courante, continuations
conditionnelles, attributions, statistiques Lichess et evaluation Stockfish. Une future architecture
pourra introduire des seams `evidence_aggregator` et `consistency_checker`; ils n'existent pas encore
dans le runtime. La provenance reste principalement attachee aux blocs de contexte ; le contrat ne
force pas encore chaque affirmation finale a designer la preuve qui la justifie.

Avec plusieurs sources et des niveaux de confiance differents, une validation globale de la reponse
ne suffit pas. Une phrase peut melanger une idee Wikibooks, une statistique Lichess et une conclusion
tactique Stockfish. Le systeme doit rendre cette composition explicite.

## Decision

1. **Assembler un `EvidencePack` avant le coach.** Le backend transforme les faits disponibles en
   preuves numerotees et structurees. Chaque preuve porte au minimum :

   - `id` stable dans le run (`F1`, `P2`, `S1`, `T1`, etc.) ;
   - `kind` (`fact`, `prose`, `stat`, `engine`, `line`) ;
   - `claim` ou contenu normalise ;
   - source, URL, licence et niveau de confiance ;
   - position/FEN, coup ou ligne associee lorsque pertinent ;
   - contraintes d'utilisation (`current`, `conditional`, `tactical`).

   Les identifiants ne sont valides que pour le run courant. Une preuve enfant reste conditionnelle
   et ne peut pas justifier une affirmation sur la position courante sans le coup d'entree.

2. **Le coach cite les preuves.** Le prompt et le contrat de sortie demandent une liste de references
   d'evidence pour chaque claim. Une phrase peut citer plusieurs preuves, mais une preuve de prose ne
   suffit pas a elle seule pour affirmer une sequence tactique. Stockfish reste requis pour le mot
   « piege » selon l'ADR 0010.

3. **Verifier les claims cote backend.** Le `ClaimVerifier` deterministe controle :

   - que chaque identifiant cite existe dans l'`EvidencePack` ;
   - que la preuve est autorisee pour le type de claim ;
   - que les coups et lignes sont legaux avec `python-chess` ;
   - que la relation `current` / `conditional` est respectee ;
   - que les metadonnees de provenance et de licence sont presentes ;
   - que les claims tactiques ont une preuve moteur compatible ;
   - que les preuves citees ne sont pas contradictoires sans attribution explicite.

4. **Correction par regeneration contrainte.** Une phrase invalide est retiree ou regeneree avec les
   preuves autorisees. Apres un nombre de tentatives borne, le systeme revient au
   `ConservativeCoachService` et ajoute un label diagnostique (`coach_claim_verification_failed`).
   Il ne patche pas silencieusement une phrase deja produite.

5. **Le chemin imperatif reste la reference.** `EvidencePack` et `ClaimVerifier` sont des services
   testables sans Ollama, LangGraph, Milvus ou Stockfish reels. Le graphe LangGraph orchestre leurs
   appels mais ne contient pas leur logique metier.

6. **Stockfish reste conditionnel en V1.** Le pack utilise l'evaluation disponible dans le run ;
   Stockfish est appele selon le plan actuel (sortie de theorie, manque de candidats ou confiance
   faible) et reutilise le cache existant. Un planner V2 peut demander une evaluation courte
   systematique si une mesure de latence et de valeur le justifie.

## Contrat illustratif

```json
{
  "evidence": [
    {
      "id": "F1",
      "kind": "engine",
      "claim": "Stockfish prefere Nf3 a depth 14",
      "source": "stockfish",
      "position": "current",
      "allowed_claims": ["evaluation", "candidate"]
    },
    {
      "id": "P2",
      "kind": "prose",
      "claim": "La pression sur e5 est une idee de la Ruy Lopez",
      "source": "wikibooks-chess-opening-theory",
      "source_url": "https://en.wikibooks.org/wiki/...",
      "license_or_terms": "CC BY-SA 4.0",
      "position": "current",
      "allowed_claims": ["strategic_explanation"]
    }
  ],
  "claims": [
    {"text": "Le fou met la pression sur e5.", "evidence_ids": ["P2"]},
    {"text": "Nf3 est le candidat prefere ici.", "evidence_ids": ["F1"]}
  ]
}
```

Le format exact de l'API reste a implementer ; cet exemple fixe la frontiere et les invariants,
pas un schema public definitif.

## Evaluation

Le harnais doit mesurer au minimum :

- taux de claims correctement attribues ;
- taux de claims sans preuve ;
- taux de coups illegaux ou de mauvaises references ;
- taux de faux « courant » provenant d'une prose conditionnelle ;
- taux de fallback apres regeneration ;
- latence et nombre de generations.

Les cas doivent couvrir les intentions, les niveaux pedagogiques, les sources contradictoires,
les questions francaises et les positions hors theorie. Le jeu Eval V2 existant est le point de
depart, mais il doit etre etendu avant de conclure sur la qualite du coach.

## Consequences

- Les attributions deviennent verifiables au niveau de la phrase et non seulement du panneau source.
- Le coach gagne une sortie plus sure mais peut fallbacker plus souvent.
- Les sources de qualite differente peuvent etre exposees sans leur donner la meme autorite.
- Une future ingestion de forums ou de litterature peut imposer des preuves `opinion` ou `secondary`,
  sans les confondre avec un fait moteur ou une source canonique.

## References

- `docs/adr/0007-llm-coach-synthesis.md` : coach contraint et fallback.
- `docs/adr/0008-coach-reference-language.md` : references coach et validation.
- `docs/adr/0009-langgraph-orchestration-and-deterministic-frontier.md` : graphe mince.
- `docs/adr/0010-bounded-agentic-investigation-tool.md` : preuve Stockfish pour un piege.
- `docs/runbooks/RAG.md` : `CoachContext`, attribution et Eval V2.
