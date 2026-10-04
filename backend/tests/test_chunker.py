import pytest

from backend.app.ingestion.chunker import (
    ChunkSection,
    ChunkSource,
    ChunkerError,
    chunk_source,
    reconstruct_page,
    utf8_length,
)


def _source(**overrides: object) -> ChunkSource:
    defaults: dict = {
        "source": "wikibooks",
        "page_title": "Chess Opening Theory/Sicilian Defence",
        "source_url": "https://en.wikibooks.org/wiki/Chess_Opening_Theory/Sicilian_Defence",
        "license_or_terms": "CC BY-SA",
        "opening_name": "Sicilian Defence",
        "eco_code": "B20",
        "page_text": "The Sicilian Defence is the most popular reply to 1. e4.",
        "sections": (
            ChunkSection(title="Concepts", text="Black fights for the centre asymmetrically."),
            ChunkSection(title="Main lines", text="Najdorf, Dragon and Scheveningen are the sharpest."),
        ),
    }
    defaults.update(overrides)
    return ChunkSource(**defaults)  # type: ignore[arg-type]


def test_page_granularity_returns_one_chunk_with_page_text() -> None:
    chunks = chunk_source(_source(), granularity="page", max_bytes=1000)

    assert len(chunks) == 1
    assert chunks[0].section_title == "Chess Opening Theory/Sicilian Defence"
    assert chunks[0].page_id == "wikibooks::Chess Opening Theory/Sicilian Defence"
    assert chunks[0].section_index is None
    assert chunks[0].part_index == 0
    assert "The Sicilian Defence is the most popular reply" in chunks[0].text


def test_section_granularity_returns_one_chunk_per_section_with_ordering() -> None:
    chunks = chunk_source(_source(), granularity="section", max_bytes=1000)

    assert [chunk.section_title for chunk in chunks] == ["Concepts", "Main lines"]
    assert [chunk.section_index for chunk in chunks] == [0, 1]
    assert all(chunk.page_id == "wikibooks::Chess Opening Theory/Sicilian Defence" for chunk in chunks)
    assert "asymmetrically" in chunks[0].text
    assert chunks[0].text.startswith("Chess Opening Theory/Sicilian Defence")


def test_section_granularity_falls_back_to_page_without_sections() -> None:
    chunks = chunk_source(_source(sections=()), granularity="section", max_bytes=1000)

    assert len(chunks) == 1
    assert "most popular reply" in chunks[0].text


def test_section_granularity_skips_empty_sections() -> None:
    source = _source(
        sections=(
            ChunkSection(title="Empty", text="   "),
            ChunkSection(title="Kept", text="Real content."),
        )
    )

    chunks = chunk_source(source, granularity="section", max_bytes=1000)

    assert [chunk.section_title for chunk in chunks] == ["Kept"]
    assert [chunk.section_index for chunk in chunks] == [0]


def test_oversized_section_splits_without_losing_content() -> None:
    body = " ".join(f"mot{i}" for i in range(400))
    source = _source(sections=(ChunkSection(title="Long", text=body),))

    chunks = chunk_source(source, granularity="section", max_bytes=200)

    assert len(chunks) > 1
    assert [chunk.part_index for chunk in chunks] == list(range(len(chunks)))
    assert all(utf8_length(chunk.text) <= 200 for chunk in chunks)
    for word in body.split():
        assert any(word in chunk.text for chunk in chunks)
    assert body.split()[-1] in chunks[-1].text


def test_oversized_page_is_rejected_not_clipped() -> None:
    source = _source(sections=(), page_text="x" * 500)

    with pytest.raises(ChunkerError):
        chunk_source(source, granularity="page", max_bytes=100)


def test_multibyte_text_respects_the_byte_budget() -> None:
    body = "é" * 300
    source = _source(sections=(ChunkSection(title="Accents", text=body),))

    chunks = chunk_source(source, granularity="section", max_bytes=120)

    assert all(utf8_length(chunk.text) <= 120 for chunk in chunks)
    assert sum(chunk.text.count("é") for chunk in chunks) == 300


def test_reconstruct_page_orders_sections_and_parts() -> None:
    chunks = chunk_source(_source(), granularity="section", max_bytes=1000)

    reconstructed = reconstruct_page(list(reversed(chunks)))

    assert reconstructed.index("Black fights") < reconstructed.index("Najdorf")
    assert reconstructed == (
        "Black fights for the centre asymmetrically.\n\n"
        "Najdorf, Dragon and Scheveningen are the sharpest."
    )


def test_metadata_is_propagated_to_every_chunk() -> None:
    chunks = chunk_source(_source(), granularity="section", max_bytes=1000)

    assert {chunk.source for chunk in chunks} == {"wikibooks"}
    assert {chunk.eco_code for chunk in chunks} == {"B20"}
    assert {chunk.opening_name for chunk in chunks} == {"Sicilian Defence"}
    assert {chunk.license_or_terms for chunk in chunks} == {"CC BY-SA"}
    assert all(chunk.source_url for chunk in chunks)


def test_ids_ignore_mapping_and_classification_metadata() -> None:
    first = chunk_source(_source(opening_node_id="old", intent="plan", is_misc=False), granularity="section", max_bytes=1000)
    second = chunk_source(_source(opening_node_id="new", intent="variation", side="white"), granularity="section", max_bytes=1000)

    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]


def test_ids_are_deterministic_and_distinct() -> None:
    first = chunk_source(_source(), granularity="section", max_bytes=1000)
    second = chunk_source(_source(), granularity="section", max_bytes=1000)

    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert len({chunk.id for chunk in first}) == len(first)
