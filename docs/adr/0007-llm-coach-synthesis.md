# Synthèse coach par LLM local

Status: accepted (2026-10-05, suite au cablage du coach déterministe, à la correction du routeur TypeSafe et au découpage progressif des runs)

Décision structurante pour la phase coach. Cette ADR concrétise la ligne « Coach LLM » et « Coach contraint » de l'ADR 0006.

## Contexte

Le pipeline RAG produit maintenant un `CoachContext` structuré et sourcé (position courante, passages courants, continuations conditionnelles, attributions, stats Lichess, Stockfish). Le `ConservativeCoachService` actuel est un template déterministe : il colle les chunks Wikibooks bruts avec un heading et des marqueurs `[source: ...]`. Il ne trahit pas les sources, mais il reste en anglais, peu naturel et indifférent au niveau pédagogique.

Le provider LLM configure est une brique du coach (ADR 0002, ADR 0006). Le provider par defaut
actuel est NVIDIA NIM; Ollama et Mistral sont des options configurees dans `config.toml`. Il est
temps d'utiliser le provider choisi pour reformuler le `CoachContext` en français, adapté au niveau
choisi, tout en restant strictement ancré aux sources.

## Décisions

1. **Service de coach par LLM par défaut.** `LlmCoachService` implémente le seam `CoachService` et remplace `ConservativeCoachService` comme renderer par défaut de `coach_explanation`.
2. **Prompt contraint et source-bounded.** Le prompt inclut :
   - le niveau pédagogique (`debutant`, `intermediaire`, `avance`) ;
   - le contexte de position (ouverture, ECO, ligne jouée) ;
   - les passages RAG avec leurs attributions ;
   - les coups recommandés par l'explorateur ;
   - les stats Lichess et l'évaluation Stockfish si présente ;
   - l'instruction explicite de répondre en français, de s'appuyer uniquement sur les faits fournis et de ne pas inventer de faits. Les métadonnées de source restent disponibles dans le contexte du prompt, mais le texte final n'est pas obligé de recopier des marqueurs de citation.
3. **Structure obligatoire du coach.** Le prompt système impose une trame pédagogique (`Plan simple`, `Idée principale`, `Coups à regarder`, `Ce que disent les stats`) pour éviter que le LLM ne se contente de répéter les statistiques.
4. **Validation minimale côté backend.** La réponse LLM doit être non vide et rester sous une longueur plafond. L'absence de marqueur `[source: ...]` ne bloque plus la réponse : la provenance reste lisible dans les panneaux d'ouverture, de contexte pédagogique, de statistiques et dans les fallbacks.
5. **Fallback immédiat vers le template déterministe.** Si Ollama est indisponible, si le modèle n'est pas chargé, en cas de timeout, de JSON invalide, de réponse vide, de limite de génération ou de métadonnées RAG incomplètes, `LlmCoachService` appelle `ConservativeCoachService.explain` avec un label diagnostique : `llm_coach_unavailable`, `llm_coach_timeout`, `llm_coach_empty`, `llm_coach_too_long` ou `llm_coach_source_metadata`.
6. **AnalysisRun séparé du rendu coach.** `POST /api/analyze-position` produit uniquement les facts Explorer et persiste un `AnalysisRun` dans la collection MongoDB `analysis_runs`. Les résultats Stockfish, RAG et coach sont ajoutés atomiquement par famille.
7. **Endpoints progressifs et idempotents.** `POST /api/stockfish/analyze-run` et `POST /api/rag-context` lisent le run et ne rappellent jamais les autres familles. `POST /api/coach-explanation` accepte `{run_id, level}`, reconstruit le `CoachContext` depuis les artefacts persistants et ne rappelle aucune source externe.
8. **Streaming SSE du coach.** `GET /api/analysis-runs/{run_id}/coach/stream` utilise `LLMProvider.generate_stream` et emet `start`, `token`, `done` ou `error`. Une deconnexion annule la generation et remet le statut a `pending`; un run deja termine est rejoue depuis MongoDB.
9. **Frontend progressif.** Angular affiche Explorer des la premiere reponse, lance RAG et Stockfish en parallele, puis ouvre le flux SSE coach. Les anciens flux sont fermes quand la position change.
10. **Clients HTTP en lifespan.** `LichessExplorerClient` et le `LLMProvider` configure sont créés dans le `lifespan` FastAPI et partagés via `app.state` pour bénéficier du pool de connexions HTTPX. Le provider coach utilise `llm.coach_timeout_seconds`, un timeout plus court que `llm.timeout_seconds`, afin de limiter l'impact d'un provider lent.
11. **LangGraph hors du service coach.** La synthèse reste un service impératif derrière le seam
    `CoachService`. Selon l'ADR 0009 acceptée, LangGraph orchestre le pipeline dans un module séparé
    et n'entre pas dans `CoachService`.
12. **Seam testable.** Le client LLM est injectable (`LLMProvider` protocol) pour permettre des tests avec `httpx.MockTransport` ou un fake, sans démarrer Ollama.

## Conséquences

- `coach_explanation` peut désormais être une prose française naturelle, adaptée au niveau, sans imposer de marqueurs de source dans le texte ; l'attribution reste visible dans les panneaux de données associés.
- L'évaluation Eval V2 doit être relue : la métrique `coach_usable_context_rate` doit rester au-dessus du gate (0.80) ; `false_current_line` doit rester à 0. Une régression due à une reformulation trop créative doit être traitée comme un bug.
- `docs/ARCHITECTURE.md` et `docs/RISKS.md` doivent documenter les labels diagnostiques des fallbacks coach.
- Le pipeline reste déterministe quand le provider configure est absent : l'analyse ne tombe jamais en erreur.
- Le frontend affiche les données de l'explorateur immédiatement, même si le coach détaillé est encore en cours.
