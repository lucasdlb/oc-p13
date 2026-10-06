"""Pure prompt assembly for grounded coach responses."""

import json

from backend.app.services.retrieval_contracts import (
    CoachContext,
    CoachProsePassage,
    CoachSourceAttribution,
)


MAX_COACH_SOURCE_CHARS = 3000


def system_prompt() -> str:
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


def build_prompt(context: CoachContext, level: str) -> str:
    position = context.current_position
    lines: list[str] = []
    if context.question:
        lines.extend(["QUESTION DE L'UTILISATEUR A TRAITER EN PRIORITE :", context.question, ""])
    lines.extend([
        f"Niveau : {level}",
        f"Ouverture : {position.opening_name or 'non identifiee'} ({position.eco_code or '?'})",
        f"Ligne jouee : {position.pgn or position.fen or 'non disponible'}",
    ])
    if context.question:
        lines.extend(["", "Question de l'utilisateur :", context.question])
    lines.extend(["", "Passages sources :"])
    sources: dict[str, CoachSourceAttribution] = {
        source.chunk_id: source for source in context.source_attributions
    }
    for passage in context.current_prose:
        lines.append(f"- Position actuelle : {_render_passage(passage, sources)}")
    for continuation in context.candidate_continuations:
        for passage in continuation.prose:
            lines.append(f"- Apres {continuation.entry_move} : {_render_passage(passage, sources)}")
    if context.recommended_moves:
        lines.extend(["", "Coups recommandes par l'explorateur (SAN -> UCI, partage) :"])
        for move in context.recommended_moves:
            share = move.get("move_share")
            games = move.get("games")
            share_text = f"{share:.1%}" if isinstance(share, float) else "?"
            games_text = str(games) if games is not None else "?"
            lines.append(f"- {move.get('san', '?')} ({move.get('uci', '?')}) : {share_text} des parties, {games_text} parties")
    lines.extend(["", "References de coups autorisees (UCI obligatoire dans le langage code) :"])
    for move in allowed_move_records(context):
        lines.append(f"- {move['san']} -> {move['uci']}")
    if context.lichess_stats:
        lines.extend(["", "Statistiques Lichess (a utiliser comme evidence, pas comme reponse) :"])
        lines.append(json.dumps(context.lichess_stats, ensure_ascii=False))
    if context.stockfish:
        lines.extend(["", "Evaluation Stockfish :", json.dumps(context.stockfish, ensure_ascii=False)])
    lines.extend(["", "Consignes finales obligatoires :"])
    lines.append("- Repondez uniquement en francais, en Markdown simple, avec les quatre sections demandees.")
    lines.append("- Visez entre 100 et 220 mots : chaque section doit contenir au moins deux phrases completes.")
    lines.append("- Dans 'Coups a regarder', expliquez chaque coup en une courte phrase ; ne donnez pas une liste de coups sans explication.")
    lines.append("- Pour chaque coup autorise cite, utilisez exactement un marqueur move avec son UCI ; ne sortez jamais un coup invente et utilisez son label SAN exact (ex. Nc3, pas c3).")
    allowed = allowed_move_records(context)
    if allowed:
        example = allowed[0]
        lines.append(f"- Exemple obligatoire de syntaxe : [[move:uci={example['uci']},label={example['san']}]].")
    lines.append("- Pour une case strategique citee par les sources et non un coup, utilisez [[square:sq=e5,label=e5]]. N'utilisez pas square automatiquement pour l'origine ou la destination d'un coup et n'ecrivez pas de marqueur move pour une simple case.")
    lines.append("- N'ajoutez aucune explication des consignes et ne produisez pas de bloc de code.")
    if context.question:
        lines.extend(["", "Rappel prioritaire : repondez d'abord a la question de l'utilisateur :", context.question])
    return "\n".join(lines)


def allowed_move_records(context: CoachContext) -> list[dict[str, str]]:
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


def _render_passage(passage: CoachProsePassage, sources: dict[str, CoachSourceAttribution]) -> str:
    source = sources[passage.source_chunk_id]
    label = source.section_title or source.canonical_title
    text = " ".join(passage.text.split())
    if len(text) > MAX_COACH_SOURCE_CHARS:
        text = text[:MAX_COACH_SOURCE_CHARS].rstrip() + " [...]"
    return f"{text} (reference: {label})"
