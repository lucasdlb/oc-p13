# Synthèse coach par LLM local

Status: accepted (2026-10-04, suite au cablage du coach déterministe et à la correction du routeur TypeSafe)

Décision structurante pour la phase coach. Cette ADR concrétise la ligne « Coach LLM » et « Coach contraint » de l'ADR 0006.

## Contexte

Le pipeline RAG produit maintenant un `CoachContext` structuré et sourcé (position courante, passages courants, continuations conditionnelles, attributions, stats Lichess, Stockfish). Le `ConservativeCoachService` actuel est un template déterministe : il colle les chunks Wikibooks bruts avec un heading et des marqueurs `[source: ...]`. Il ne trahit pas les sources, mais il reste en anglais, peu naturel et indifférent au niveau pédagogique.

Le LLM local Ollama `qwen2.5:7b-instruct` est déjà une brique non négociable (ADR 0002, ADR 0006). Il est temps de l'utiliser pour reformuler le `CoachContext` en français, adapté au niveau choisi, tout en restant strictement ancré aux sources.

## Décisions

1. **Service de coach par LLM par défaut.** `LlmCoachService` implémente le seam `CoachService` et remplace `ConservativeCoachService` comme renderer par défaut de `coach_explanation`.
2. **Prompt contraint et source-bounded.** Le prompt inclut :
   - le niveau pédagogique (`debutant`, `intermediaire`, `avance`) ;
   - le contexte de position (ouverture, ECO, ligne jouée) ;
   - les passages RAG avec leurs attributions ;
   - les stats Lichess et l'évaluation Stockfish si présente ;
   - l'instruction explicite de répondre en français, de citer les sources via les marqueurs fournis, et de ne pas inventer de faits.
3. **Validation minimale côté backend.** La réponse LLM doit être non vide, rester sous une longueur plafond, et conserver au moins une citation de source. En cas de non-respect, on bascule.
4. **Fallback immédiat vers le template déterministe.** Si Ollama est indisponible, si le modèle n'est pas chargé, en cas de timeout, d'erreur HTTP, de JSON invalide ou de réponse rejetée par la validation, `LlmCoachService` appelle `ConservativeCoachService.explain` et ajoute `llm_coach_unavailable` à `fallbacks_used`.
5. **Pas de LangGraph.** La synthèse reste un service impératif derrière le seam `CoachService`, conformément à l'ADR 0006. LangGraph ne sera introduit qu'après stabilisation de ce chemin.
6. **Seam testable.** Le client LLM est injectable (`LLMProvider` protocol) pour permettre des tests avec `httpx.MockTransport` ou un fake, sans démarrer Ollama.

## Conséquences

- `coach_explanation` peut désormais être une prose française naturelle, adaptée au niveau, sans perdre l'attribution des sources.
- L'évaluation Eval V2 doit être relue : la métrique `coach_usable_context_rate` doit rester au-dessus du gate (0.80) ; `false_current_line` doit rester à 0. Une régression due à une reformulation trop créative doit être traitée comme un bug.
- `docs/ARCHITECTURE.md` et `docs/RISKS.md` doivent documenter le nouveau fallback `llm_coach_unavailable`.
- Le pipeline reste déterministe quand Ollama est absent : l'analyse ne tombe jamais en erreur.
