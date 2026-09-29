from dataclasses import dataclass

import chess

from backend.app.models.analysis import Opening, RecommendedMove


@dataclass(frozen=True)
class OpeningBookEntry:
    eco: str
    name: str
    pgn: str
    uci: tuple[str, ...]
    epd: str
    source: str
    recommended_moves: tuple[RecommendedMove, ...]
    context: str


@dataclass(frozen=True)
class OpeningMatch:
    opening: Opening
    recommended_moves: tuple[RecommendedMove, ...]
    context: str
    matched: bool


DEMO_OPENING_SOURCE = "demo-opening-seed"


OPENING_BOOK: tuple[OpeningBookEntry, ...] = (
    OpeningBookEntry(
        eco="B00",
        name="King's Pawn Game",
        pgn="1. e4",
        uci=("e2e4",),
        epd="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
        source=DEMO_OPENING_SOURCE,
        recommended_moves=(
            RecommendedMove(
                uci="e7e5",
                san="...e5",
                description="Conteste le centre et ouvre les diagonales des pieces noires.",
                source=DEMO_OPENING_SOURCE,
            ),
            RecommendedMove(
                uci="c7c5",
                san="...c5",
                description="Transforme la partie en Sicilienne avec un jeu asymetrique.",
                source=DEMO_OPENING_SOURCE,
            ),
        ),
        context="Apres 1. e4, les blancs occupent le centre et liberent la dame et le fou roi.",
    ),
    OpeningBookEntry(
        eco="C44-C60",
        name="Italian and Spanish Game family",
        pgn="1. e4 e5 2. Nf3 Nc6",
        uci=("e2e4", "e7e5", "g1f3", "b8c6"),
        epd="r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq -",
        source=DEMO_OPENING_SOURCE,
        recommended_moves=(
            RecommendedMove(
                uci="f1b5",
                san="Bb5",
                description="Met la pression sur le cavalier c6 et entre dans les idees de l'Espagnole.",
                source=DEMO_OPENING_SOURCE,
            ),
            RecommendedMove(
                uci="f1c4",
                san="Bc4",
                description="Vise f7 et developpe rapidement le fou dans les lignes italiennes.",
                source=DEMO_OPENING_SOURCE,
            ),
        ),
        context="Apres 1. e4 e5 2. Nf3 Nc6, les blancs choisissent souvent entre l'Espagnole et l'Italienne.",
    ),
    OpeningBookEntry(
        eco="C60",
        name="Ruy Lopez",
        pgn="1. e4 e5 2. Nf3 Nc6 3. Bb5",
        uci=("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"),
        epd="r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq -",
        source=DEMO_OPENING_SOURCE,
        recommended_moves=(
            RecommendedMove(
                uci="a7a6",
                san="...a6",
                description="Questionne le fou b5 et prepare souvent ...b5 pour gagner de l'espace.",
                source=DEMO_OPENING_SOURCE,
            ),
            RecommendedMove(
                uci="g8f6",
                san="...Nf6",
                description="Developpe une piece et attaque le pion e4 dans l'esprit de la Defense berlinoise.",
                source=DEMO_OPENING_SOURCE,
            ),
        ),
        context="L'Espagnole met une pression durable sur le centre noir en attaquant le defenseur du pion e5.",
    ),
)


def match_opening(moves: list[str], fen: str) -> OpeningMatch:
    exact_uci_match = _find_exact_uci_match(moves)
    if exact_uci_match:
        return _to_match(exact_uci_match)

    exact_epd_match = _find_exact_epd_match(fen)
    if exact_epd_match:
        return _to_match(exact_epd_match)

    prefix_match = _find_prefix_match(moves)
    if prefix_match:
        return _to_match(prefix_match)

    return OpeningMatch(
        opening=Opening(
            eco="?",
            name="Ouverture inconnue",
            matched=False,
            source="local-opening-matcher",
        ),
        recommended_moves=(),
        context="La ligne jouee n'est pas encore presente dans le seed local d'ouvertures.",
        matched=False,
    )


def _to_match(entry: OpeningBookEntry) -> OpeningMatch:
    return OpeningMatch(
        opening=Opening(
            eco=entry.eco,
            name=entry.name,
            matched=True,
            source=entry.source,
        ),
        recommended_moves=entry.recommended_moves,
        context=entry.context,
        matched=True,
    )


def _find_exact_uci_match(moves: list[str]) -> OpeningBookEntry | None:
    move_tuple = tuple(moves)
    return next((entry for entry in OPENING_BOOK if entry.uci == move_tuple), None)


def _find_exact_epd_match(fen: str) -> OpeningBookEntry | None:
    epd = chess.Board(fen).epd()
    return next((entry for entry in OPENING_BOOK if entry.epd == epd), None)


def _find_prefix_match(moves: list[str]) -> OpeningBookEntry | None:
    candidates = [
        entry
        for entry in OPENING_BOOK
        if len(entry.uci) < len(moves) and tuple(moves[: len(entry.uci)]) == entry.uci
    ]
    return max(candidates, key=lambda entry: len(entry.uci), default=None)
