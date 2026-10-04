import pytest

from backend.app.ingestion.adapters import (
    ChessOpeningsAdapter,
    WikibooksAdapter,
    WikibooksAdapterError,
    WikibooksPage,
)
from backend.app.ingestion.chunker import chunk_source


CHESS_OPENINGS_TSV = "\n".join(
    [
        "eco\tname\tpgn",
        "B90\tSicilian Defence, Najdorf Variation\t1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6",
        "C60\tRuy Lopez\t1. e4 e5 2. Nf3 Nc6 3. Bb5",
    ]
)

WIKITEXT = """
The '''Sicilian Defence''' is a chess opening beginning with 1. e4 c5.<ref name="x">ref</ref>
{{Infobox chess opening|name=Sicilian}}
It is the most popular reply to 1. e4.

== Concepts ==
Black fights for the centre. See [[Chess Opening Theory/1. e4|1. e4]] for context.
<!-- a comment -->
=== Najdorf ===
The Najdorf is sharp and double-edged.

== Main lines ==
Playable moves include [https://example.org 2. Nf3] and 2. Nc3.
"""


def test_chess_openings_parses_one_source_per_row() -> None:
    sources = ChessOpeningsAdapter().parse(CHESS_OPENINGS_TSV)

    assert [source.eco_code for source in sources] == ["B90", "C60"]
    assert sources[0].opening_name == "Sicilian Defence, Najdorf Variation"
    assert sources[0].line_pgn == "1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6"
    assert sources[0].source == "lichess-org/chess-openings"
    assert sources[0].license_or_terms == "CC0-1.0"
    assert sources[0].sections == ()


def test_chess_openings_respects_limit_and_skips_short_rows() -> None:
    text = CHESS_OPENINGS_TSV + "\nbroken\trow\n"
    sources = ChessOpeningsAdapter().parse(text, limit=1)

    assert len(sources) == 1
    assert sources[0].eco_code == "B90"


def test_chess_openings_skips_every_header_when_files_are_concatenated() -> None:
    text = CHESS_OPENINGS_TSV + "\n" + CHESS_OPENINGS_TSV

    sources = ChessOpeningsAdapter().parse(text)

    assert [source.eco_code for source in sources] == ["B90", "C60", "B90", "C60"]


def test_chess_openings_produces_one_page_chunk_per_row() -> None:
    chunks = [chunk_source(source, granularity="page") for source in ChessOpeningsAdapter().parse(CHESS_OPENINGS_TSV)]

    assert len(chunks) == 2
    assert len(chunks[0]) == 1
    assert "B90" in chunks[0][0].text
    assert "Najdorf" in chunks[0][0].text


def test_wikibooks_splits_sections_and_keeps_the_lead() -> None:
    source = WikibooksAdapter().parse(
        WikibooksPage(title="Chess Opening Theory/1. e4/1...c5", wikitext=WIKITEXT),
        eco_code="B20",
        opening_name="Sicilian Defence",
    )

    assert [section.title for section in source.sections] == [None, "Concepts", "Najdorf", "Main lines"]
    assert source.eco_code == "B20"
    assert source.opening_name == "Sicilian Defence"
    assert source.license_or_terms == "CC BY-SA 4.0"


def test_wikibooks_cleans_markup() -> None:
    source = WikibooksAdapter().parse(
        WikibooksPage(title="T", wikitext=WIKITEXT),
        eco_code="B20",
        opening_name="Sicilian Defence",
    )

    assert "{{Infobox" not in source.page_text
    assert "<ref" not in source.page_text
    assert "<!--" not in source.page_text
    assert "'''" not in source.page_text
    assert "[[Chess Opening Theory/1. e4|1. e4]]" not in source.page_text
    assert "1. e4" in source.page_text
    assert "2. Nf3" in source.page_text


def test_wikibooks_sections_chunk_with_their_titles() -> None:
    source = WikibooksAdapter().parse(
        WikibooksPage(title="Chess Opening Theory/1. e4/1...c5", wikitext=WIKITEXT),
        eco_code="B20",
        opening_name="Sicilian Defence",
    )

    chunks = chunk_source(source, granularity="section")

    assert "Najdorf" in [chunk.section_title for chunk in chunks]
    najdorf = next(chunk for chunk in chunks if chunk.section_title == "Najdorf")
    assert "double-edged" in najdorf.text
    assert najdorf.eco_code == "B20"


def test_wikibooks_keeps_prose_and_excludes_layout_and_navigation() -> None:
    wikitext = """
{{Chess Opening Theory/Position
|Queen's gambit
|responses=<br>
* [[/2...dxc4|2...dxc4 - accepted]]
}}
== 2. c4 - Queen's gambit ==
First pedagogical paragraph.

Second paragraph with [[/2...dxc4|'''2...dxc4''']] and [[/3. Nc3/]].

* First useful idea
* Second useful idea

== Theory table ==
{{ChessTable}}
<table><tr><td>Exchange Variation</td><td>Bxc6</td><td>dxc6</td></tr></table>

== References ==
* A book, ISBN 123

== See also ==
[[fi:Shakki/rnbqkbnr;ppp1pppp]]
[[Category:Chess openings]]
"""

    source = WikibooksAdapter().parse(
        WikibooksPage(title="Chess Opening Theory/1. d4/1...d5/2. c4", wikitext=wikitext),
        eco_code="D06",
        opening_name="Queen's Gambit",
    )

    assert [section.title for section in source.sections] == ["2. c4 - Queen's gambit"]
    assert source.sections[0].text == (
        "First pedagogical paragraph.\n\n"
        "Second paragraph with 2...dxc4 and 3. Nc3.\n\n"
        "- First useful idea\n"
        "- Second useful idea"
    )
    assert source.page_text == (
        "2. c4 - Queen's gambit\n\n"
        "First pedagogical paragraph.\n\n"
        "Second paragraph with 2...dxc4 and 3. Nc3.\n\n"
        "- First useful idea\n"
        "- Second useful idea"
    )
    assert "Bxc6dxc6" not in source.page_text
    assert "ISBN" not in source.page_text
    assert "fi:Shakki" not in source.page_text


def test_wikibooks_rejects_pages_without_clean_pedagogical_prose() -> None:
    wikitext = """
{{Chess Opening Theory/Position|Queen's gambit}}
== Theory table ==
<table><tr><td>Bxc6</td><td>dxc6</td></tr></table>
== References ==
* A book
"""

    with pytest.raises(WikibooksAdapterError, match="no pedagogical prose"):
        WikibooksAdapter().parse(WikibooksPage(title="Only layout", wikitext=wikitext))


def test_wikibooks_rejects_residual_wiki_markup() -> None:
    with pytest.raises(WikibooksAdapterError, match="residual MediaWiki markup"):
        WikibooksAdapter().parse(
            WikibooksPage(title="Broken", wikitext="== Ideas ==\nUseful prose {{broken")
        )
