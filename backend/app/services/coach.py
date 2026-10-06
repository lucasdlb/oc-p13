"""Coach service seam.

`CoachService` is the renderer protocol used by `analyze_position`.
`ConservativeCoachService` is the deterministic, source-bound baseline.
`LlmCoachService` delegates to an `LLMProvider` for natural French prose and
falls back to the conservative template when the LLM cannot be trusted.
"""

import json
import logging
import re
from collections.abc import Iterator
from typing import NoReturn, Protocol, runtime_checkable

import chess

from backend.app.services.llm import (
    LLMProvider,
    LLMProviderEmptyError,
    LLMProviderError,
    LLMProviderLengthError,
    LLMProviderTimeoutError,
)
from backend.app.services.retrieval_contracts import (
    CoachContext,
    CoachProsePassage,
    CoachSourceAttribution,
)
from backend.app.services.coach_references import sanitize_coach_references

MAX_LLM_COACH_CHARS = 4000
MAX_COACH_SOURCE_CHARS = 3000
logger = logging.getLogger("backend.coach")
_COACH_MARKER_PATTERN = re.compile(r"\[\[[a-z]+:[^\[\]]*\]\]", re.IGNORECASE)
_SAN_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:O-O-O|O-O|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_UCI_TOKEN_PATTERN = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$", re.IGNORECASE)
_SQUARE_TOKEN_PATTERN = re.compile(r"[a-h][1-8]", re.IGNORECASE)
_SQUARE_CONTEXT_PATTERN = re.compile(
    r"\b(?:"
    r"cases?(?:\s+(?:centrale?|strategique|strategiques|critique|critiques|"
    r"importante|importantes|cible|cibles))?"
    r"|sur(?:\s+(?:la|les))?(?:\s+cases?)?"
    r"|pions?"
    r")\s+(?P<squares>(?:\*\*)?[a-h][1-8](?:\*\*)?"
    r"(?:\s*(?:,|ou|et)\s*(?:\*\*)?[a-h][1-8](?:\*\*)?)*)"
    ,
    re.IGNORECASE,
)


@runtime_checkable
class CoachService(Protocol):
    """Abstract seam for rendering coach prose from a grounded context."""

    def explain(self, context: CoachContext, *, level: str) -> str:
        """Return French, level-adapted prose constrained by the supplied context."""


class CoachFallbackError(Exception):
    """Raised by a coach service when it fell back to a safer renderer.

    Carries the deterministic fallback text and the label to record in
    ``fallbacks_used``.
    """

    def __init__(self, text: str, fallback_label: str) -> None:
        self.text = text
        self.fallback_label = fallback_label
        super().__init__(fallback_label)


class ConservativeCoachService:
    """Render deterministic coach prose from already-partitioned context."""

    def explain(self, context: CoachContext, *, level: str) -> str:
        _validate_context_shape(context)
        sources = _source_map(context.source_attributions)
        if not _all_passages_sourced(context, sources):
            return _fallback_explanation(context)

        heading = _position_heading(context, level)
        parts = [heading]
        if context.current_prose:
            parts.append(
                "Dans la position actuelle, "
                + " ".join(_render_passage(passage, sources) for passage in context.current_prose)
            )
        for continuation in context.candidate_continuations:
            rendered = " ".join(_render_passage(passage, sources) for passage in continuation.prose)
            side = _side_to_move_label(context)
            entry = continuation.entry_move
            if continuation.entry_uci:
                label = f"...{continuation.entry_move}" if side == "Noirs" else continuation.entry_move
                entry = f"[[move:uci={continuation.entry_uci},label={label}]]"
            prefix = "" if continuation.entry_uci else "..."
            parts.append(f"Si les {side} jouent {prefix}{entry}, {rendered}")
        if len(parts) == 1:
            return _fallback_explanation(context)
        return prepare_coach_output("\n\n".join(parts), context)


class LlmCoachService:
    """Synthesize French, level-adapted coach prose via an LLM provider."""

    def __init__(
        self,
        provider: LLMProvider,
        fallback: CoachService | None = None,
        max_length: int = MAX_LLM_COACH_CHARS,
    ) -> None:
        self._provider = provider
        self._fallback = fallback or ConservativeCoachService()
        self._max_length = max_length

    def explain(self, context: CoachContext, *, level: str) -> str:
        _validate_context_shape(context)
        sources = _source_map(context.source_attributions)
        if not _all_passages_sourced(context, sources):
            self._raise_fallback(context, level, "llm_coach_source_metadata")

        prompt = _build_prompt(context, level)
        try:
            text = self._provider.generate(prompt, system=_system_prompt())
        except LLMProviderTimeoutError as exc:
            logger.warning("LLM coach fallback llm_coach_timeout: %s", exc)
            self._raise_fallback(context, level, "llm_coach_timeout")
        except LLMProviderEmptyError as exc:
            logger.warning("LLM coach fallback llm_coach_empty: %s", exc)
            self._raise_fallback(context, level, "llm_coach_empty")
        except LLMProviderLengthError as exc:
            logger.warning("LLM coach fallback llm_coach_too_long: %s", exc)
            self._raise_fallback(context, level, "llm_coach_too_long")
        except LLMProviderError as exc:
            logger.warning("LLM coach fallback llm_coach_unavailable: %s", exc)
            self._raise_fallback(context, level, "llm_coach_unavailable")

        validated = _validate_llm_output(text, self._max_length)
        if validated is None:
            self._raise_fallback(context, level, _output_failure_label(text, self._max_length))
        return prepare_coach_output(validated, context)

    def stream_explain(self, context: CoachContext, *, level: str) -> Iterator[str]:
        """Yield grounded coach chunks while keeping the same validation seam."""
        _validate_context_shape(context)
        sources = _source_map(context.source_attributions)
        if not _all_passages_sourced(context, sources):
            self._raise_fallback(context, level, "llm_coach_source_metadata")

        try:
            chunks: list[str] = []
            for chunk in self._provider.generate_stream(
                _build_prompt(context, level),
                system=_system_prompt(),
            ):
                chunks.append(chunk)
                yield chunk
        except LLMProviderTimeoutError as exc:
            logger.warning("LLM coach fallback llm_coach_timeout: %s", exc)
            self._raise_fallback(context, level, "llm_coach_timeout")
        except LLMProviderEmptyError as exc:
            logger.warning("LLM coach fallback llm_coach_empty: %s", exc)
            self._raise_fallback(context, level, "llm_coach_empty")
        except LLMProviderLengthError as exc:
            logger.warning("LLM coach fallback llm_coach_too_long: %s", exc)
            self._raise_fallback(context, level, "llm_coach_too_long")
        except LLMProviderError as exc:
            logger.warning("LLM coach fallback llm_coach_unavailable: %s", exc)
            self._raise_fallback(context, level, "llm_coach_unavailable")
        combined = "".join(chunks)
        if _validate_llm_output(combined, self._max_length) is None:
            self._raise_fallback(context, level, _output_failure_label(combined, self._max_length))

    def _raise_fallback(self, context: CoachContext, level: str, label: str) -> NoReturn:
        text = self._fallback.explain(context, level=level)
        raise CoachFallbackError(prepare_coach_output(text, context), label)


def _validate_context_shape(context: CoachContext) -> None:
    for passage in context.current_prose:
        if passage.relation_to_position != "current":
            raise ValueError("current_prose can contain only current passages")
    for continuation in context.candidate_continuations:
        for passage in continuation.prose:
            if passage.relation_to_position != "child":
                raise ValueError("candidate continuations can contain only child passages")


def _source_map(attributions: tuple[CoachSourceAttribution, ...]) -> dict[str, CoachSourceAttribution]:
    return {source.chunk_id: source for source in attributions}


def _all_passages_sourced(context: CoachContext, sources: dict[str, CoachSourceAttribution]) -> bool:
    passages = [*context.current_prose]
    for continuation in context.candidate_continuations:
        passages.extend(continuation.prose)
    return all(_has_usable_source(passage, sources) for passage in passages)


def _has_usable_source(passage: CoachProsePassage, sources: dict[str, CoachSourceAttribution]) -> bool:
    source = sources.get(passage.source_chunk_id)
    return bool(source and source.source_url and source.license_or_terms and source.page_id)


def _position_heading(context: CoachContext, level: str) -> str:
    position = context.current_position
    if position.opening_name and position.eco_code:
        return f"Explication niveau {level}: {position.opening_name} ({position.eco_code})."
    if position.opening_name:
        return f"Explication niveau {level}: {position.opening_name}."
    return f"Explication niveau {level}: position hors theorie connue."


def _render_passage(passage: CoachProsePassage, sources: dict[str, CoachSourceAttribution]) -> str:
    source = sources[passage.source_chunk_id]
    return f"{_compact_text(passage.text)} {_source_marker(source)}"


def _render_prompt_passage(passage: CoachProsePassage, sources: dict[str, CoachSourceAttribution]) -> str:
    source = sources[passage.source_chunk_id]
    label = source.section_title or source.canonical_title
    text = _compact_text(passage.text)
    if len(text) > MAX_COACH_SOURCE_CHARS:
        text = text[:MAX_COACH_SOURCE_CHARS].rstrip() + " [...]"
    return f"{text} (reference: {label})"


def _compact_text(text: str) -> str:
    return " ".join(text.split())


def _source_marker(source: CoachSourceAttribution) -> str:
    label = source.section_title or source.canonical_title
    return f"[source: {label}, {source.license_or_terms}]"


def _fallback_explanation(context: CoachContext) -> str:
    opening = context.current_position.opening_name
    if opening:
        return (
            "Je n'ai pas assez de contexte source pour formuler une explication fiable. "
            f"Je peux seulement signaler la ligne identifiee: {opening}."
        )
    return "Je n'ai pas assez de contexte source pour formuler une explication fiable."


def _system_prompt() -> str:
    return (
        "Vous etes un coach d'echecs. Redigez une explication strictement en francais, "
        "adaptee au niveau indique. Basez-vous uniquement sur les faits fournis ; "
        "si une question de l'utilisateur est fournie, repondez-y en priorite des le debut, "
        "puis reliez la reponse au plan et aux coups de la position. "
        "ne creez rien. Utilisez les donnees structurees, le contexte pedagogique, "
        "les statistiques Lichess et Stockfish comme seules bases factuelles. "
        "Restez concis mais developpe : entre 100 et 220 mots, sans repeter les consignes.\n\n"
        "Regle de langue : traduisez et reformulez les passages sources en anglais ; "
        "ne repondez jamais en anglais, sauf pour les noms propres, les coups, les codes ECO "
        "et les marqueurs de source.\n\n"
        "Structure obligatoire (niveau debutant : 2 phrases completes par section ; "
        "niveau avance : developpez plus) :\n"
        "1. Plan simple : quel est l'objectif strategique des Blancs ou des Noirs dans cette position ?\n"
        "2. Idee principale : quelle manoeuvre ou case est importante ?\n"
        "3. Coups a regarder : citez 1 a 3 coups concrets recommandes par les sources.\n"
        "4. Ce que disent les stats : utilisez les statistiques Lichess comme evidence, "
        "pas comme reponse complete. Dites quel coup est le plus joue et ce que cela suggere.\n\n"
        "N'utilisez jamais les statistiques seules pour conclure. Expliquez d'abord l'idee, "
        "puis appuyez-la par les chiffres. Ne mentionnez pas ces consignes.\n\n"
        "References interactives : utilisez uniquement ce langage code, sans jamais deviner "
        "l'intention depuis du SAN brut. Un coup jouable est marque "
        "[[move:uci=e7e5,label=e5]]. Une case strategique est marquee "
        "[[square:sq=e5,label=e5]] et ne doit jamais etre presentee comme un coup. "
        "Une suite est marquee [[line:moves=e2e4,e7e5,g1f3,label=e4 puis ...e5 puis Nf3]]. "
        "Utilisez uniquement les UCI autorises fournis dans le contexte. Les coups des "
        "continuations sont conditionnels et doivent rester introduits par 'si'. "
        "Format de sortie : utilisez un Markdown tres simple pour la lisibilite : "
        "titres de niveau 2, paragraphes separes par une ligne vide, listes avec '- ' "
        "et gras avec '**...**'. N'utilisez pas de HTML, de tableau, de bloc de code "
        "ou de lien invente. Les retours a la ligne sont significatifs."
    )


def _build_prompt(context: CoachContext, level: str) -> str:
    position = context.current_position
    lines: list[str] = []
    if context.question:
        lines.extend(["QUESTION DE L'UTILISATEUR A TRAITER EN PRIORITE :", context.question, ""])
    lines.extend(
        [
            f"Niveau : {level}",
            f"Ouverture : {position.opening_name or 'non identifiee'} ({position.eco_code or '?'})",
            f"Ligne jouee : {position.pgn or position.fen or 'non disponible'}",
        ]
    )
    if context.question:
        lines.extend(["", "Question de l'utilisateur :", context.question])
    lines.extend([
        "",
        "Passages sources :",
    ])
    sources = _source_map(context.source_attributions)
    for passage in context.current_prose:
        lines.append(f"- Position actuelle : {_render_prompt_passage(passage, sources)}")
    for continuation in context.candidate_continuations:
        for passage in continuation.prose:
            lines.append(f"- Apres {continuation.entry_move} : {_render_prompt_passage(passage, sources)}")
    if context.recommended_moves:
        lines.extend(["", "Coups recommandes par l'explorateur (SAN -> UCI, partage) :"])
        for move in context.recommended_moves:
            san = move.get("san", "?")
            uci = move.get("uci", "?")
            share = move.get("move_share")
            games = move.get("games")
            share_text = f"{share:.1%}" if isinstance(share, float) else "?"
            games_text = str(games) if games is not None else "?"
            lines.append(f"- {san} ({uci}) : {share_text} des parties, {games_text} parties")
    lines.extend(["", "References de coups autorisees (UCI obligatoire dans le langage code) :"])
    for move in _allowed_move_records(context):
        lines.append(f"- {move['san']} -> {move['uci']}")
    if context.lichess_stats:
        lines.extend(["", "Statistiques Lichess (a utiliser comme evidence, pas comme reponse) :"])
        lines.append(json.dumps(context.lichess_stats, ensure_ascii=False))
    if context.stockfish:
        lines.extend(["", "Evaluation Stockfish :", json.dumps(context.stockfish, ensure_ascii=False)])
    lines.extend(["", "Consignes finales obligatoires :"])
    lines.append("- Repondez uniquement en francais, en Markdown simple, avec les quatre sections demandees.")
    lines.append("- Visez entre 100 et 220 mots : chaque section doit contenir au moins deux phrases completes.")
    lines.append(
        "- Dans 'Coups a regarder', expliquez chaque coup en une courte phrase ; "
        "ne donnez pas une liste de coups sans explication."
    )
    lines.append(
        "- Pour chaque coup autorise cite, utilisez exactement un marqueur move avec son UCI ; "
        "ne sortez jamais un coup invente et utilisez son label SAN exact (ex. Nc3, pas c3)."
    )
    allowed = _allowed_move_records(context)
    if allowed:
        example = allowed[0]
        lines.append(
            f"- Exemple obligatoire de syntaxe : [[move:uci={example['uci']},label={example['san']}]]."
        )
    lines.append(
        "- Pour une case strategique citee par les sources et non un coup, utilisez "
        "[[square:sq=e5,label=e5]]. N'utilisez pas square automatiquement pour l'origine ou "
        "la destination d'un coup et n'ecrivez pas de marqueur move pour une simple case."
    )
    lines.append("- N'ajoutez aucune explication des consignes et ne produisez pas de bloc de code.")
    if context.question:
        lines.extend(["", "Rappel prioritaire : repondez d'abord a la question de l'utilisateur :", context.question])
    return "\n".join(lines)


def _allowed_move_records(context: CoachContext) -> list[dict[str, str]]:
    records = [
        {"san": str(move.get("san", "?")), "uci": str(move.get("uci", ""))}
        for move in context.recommended_moves
        if move.get("uci")
    ]
    if isinstance(context.stockfish, dict) and context.stockfish.get("best_move"):
        records.append({"san": "meilleur coup Stockfish", "uci": str(context.stockfish["best_move"])})
    for continuation in context.candidate_continuations:
        if continuation.entry_uci:
            records.append({"san": continuation.entry_move, "uci": continuation.entry_uci})
    return list({record["uci"]: record for record in records}.values())


def _side_to_move_label(context: CoachContext) -> str:
    try:
        return "Blancs" if chess.Board(context.current_position.fen).turn else "Noirs"
    except ValueError:
        return "Noirs"


def sanitize_coach_output(text: str, context: CoachContext) -> str:
    """Sanitize references after a complete streamed response is assembled."""

    allowed_moves = {record["uci"] for record in _allowed_move_records(context)}
    return sanitize_coach_references(
        text,
        fen=context.current_position.fen,
        allowed_moves=allowed_moves,
    )


def prepare_coach_output(text: str, context: CoachContext) -> str:
    """Validate DSL references and recover safe links omitted by the LLM."""
    sanitized = sanitize_coach_output(text, context)
    try:
        board = chess.Board(context.current_position.fen)
    except ValueError:
        return sanitized

    legal_records = [
        record
        for record in _allowed_move_records(context)
        if _is_legal_uci(board, record["uci"])
    ]
    enriched = _annotate_line_reference(sanitized, board, context)
    enriched = _annotate_square_reference(enriched)
    for record in legal_records:
        enriched = _annotate_move_reference(enriched, record)

    if _COACH_MARKER_PATTERN.search(enriched):
        return enriched

    fallback = _interactive_reference_fallback(legal_records)
    return f"{enriched}\n\n{fallback}" if fallback else enriched


def _annotate_line_reference(text: str, board: chess.Board, context: CoachContext) -> str:
    masked = _mask_coach_markers(text)
    matches = list(_SAN_TOKEN_PATTERN.finditer(masked))
    allowed_moves = {
        record["uci"]
        for record in _allowed_move_records(context)
        if record.get("uci")
    }

    for start, first in enumerate(matches):
        candidate_board = board.copy(stack=False)
        parsed: list[tuple[str, str, str]] = []
        previous = None
        for match in matches[start:]:
            if previous is not None and not _is_sequence_gap(masked[previous.end():match.start()]):
                break
            move = _parse_move_token(candidate_board, match.group(0))
            if move is None:
                break
            parsed.append((move.uci(), match.group(0), candidate_board.san(move)))
            candidate_board.push(move)
            previous = match
            if len(parsed) < 2 or parsed[0][0] not in allowed_moves:
                continue

            label = " puis ".join(san for _, _, san in parsed)
            marker = f"[[line:moves={','.join(uci for uci, _, _ in parsed)},label={label}]]"
            return text[:first.start()] + marker + text[match.end():]

    return text


def _parse_move_token(board: chess.Board, token: str) -> chess.Move | None:
    if _UCI_TOKEN_PATTERN.fullmatch(token):
        try:
            move = chess.Move.from_uci(token.lower())
        except ValueError:
            return None
        return move if board.is_legal(move) else None

    try:
        return board.parse_san(token)
    except ValueError:
        return None


def _annotate_square_reference(text: str) -> str:
    masked = _mask_coach_markers(text)
    replacements: list[tuple[int, int, str]] = []
    for context_match in _SQUARE_CONTEXT_PATTERN.finditer(masked):
        squares = context_match.group("squares")
        squares_start = context_match.start("squares")
        for square_match in _SQUARE_TOKEN_PATTERN.finditer(squares):
            square = square_match.group(0).lower()
            start = squares_start + square_match.start()
            end = squares_start + square_match.end()
            replacements.append((start, end, f"[[square:sq={square},label={square}]]"))

    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]
    return text


def _annotate_move_reference(text: str, record: dict[str, str]) -> str:
    san = record.get("san", "").strip()
    uci = record.get("uci", "").strip().lower()
    if not san or not uci:
        return text
    for token in (san, uci):
        while True:
            masked = _mask_coach_markers(text)
            match = re.search(
                rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])",
                masked,
                re.IGNORECASE,
            )
            if not match:
                break
            marker = f"[[move:uci={uci},label={san}]]"
            text = text[:match.start()] + marker + text[match.end():]
    return text


def _interactive_reference_fallback(records: list[dict[str, str]]) -> str:
    if not records:
        return ""

    first = records[0]
    uci = first["uci"]
    san = first["san"]
    destination = uci[2:4]
    return (
        "References interactives :\n"
        f"- Coup : [[move:uci={uci},label={san}]]\n"
        f"- Case cible : [[square:sq={destination},label={destination}]]"
    )


def _mask_coach_markers(text: str) -> str:
    return _COACH_MARKER_PATTERN.sub(lambda match: " " * len(match.group(0)), text)


def _is_sequence_gap(gap: str) -> bool:
    return bool(
        re.fullmatch(
            r"\s*(?:(?:\d+\.)|puis|,|;|:|->|…|\.\.\.)*\s*",
            gap,
            re.IGNORECASE,
        )
    )


def _is_legal_uci(board: chess.Board, uci: str) -> bool:
    try:
        return board.is_legal(chess.Move.from_uci(uci))
    except ValueError:
        return False


def _validate_llm_output(text: str, max_length: int = MAX_LLM_COACH_CHARS) -> str | None:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        return None
    return cleaned


def _output_failure_label(text: str, max_length: int) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return "llm_coach_empty"
    if len(cleaned) > max_length:
        return "llm_coach_too_long"
    return "llm_coach_invalid_output"
