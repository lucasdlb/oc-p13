"""Clean the full Wikibooks snapshot and emit a quality report (ticket 04).

Consumes the versioned manifest (ticket 03). For every fetched page it runs the v2
gates and section classifier, chunks accepted sections under the byte budget,
detects duplicate/near-duplicate prose, and maps each accepted page/chunk to the
structured OpeningTree (ticket 05). It writes three artifacts and never touches
Milvus.

Run: ``uv run python -m experiments.rag.clean_report``
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend.app.ingestion.chunker import ChunkSection, ChunkSource, chunk_source, utf8_length
from backend.app.ingestion.classifier import classify_page, find_duplicates
from backend.app.ingestion.opening_mapper import map_page, refine_section
from backend.app.services.opening_tree import OpeningTree

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / ".scratch" / "rag" / "corpus" / "wikibooks-full" / "manifest.json"
DEFAULT_CORPUS_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus" / "wikibooks-full"
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus" / "wikibooks-clean"
DEFAULT_OPENING_TREE_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus" / "opening-tree"

MAX_BYTES = 16000
LICENSE = "CC BY-SA 4.0"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--opening-tree-dir", type=Path, default=DEFAULT_OPENING_TREE_DIR)
    parser.add_argument("--max-pages", type=int, default=None)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    pages = [p for p in manifest["pages"] if p["status"] == "fetched"]
    if args.max_pages is not None:
        pages = pages[: args.max_pages]

    args.output_dir.mkdir(parents=True, exist_ok=True)

    tree = OpeningTree.from_snapshot_dir(args.opening_tree_dir)

    page_records = []
    chunk_records = []
    dup_sections = []
    status_counter = Counter()
    reason_counter = Counter()
    intent_counter = Counter()
    mapping_pages = Counter()
    mapping_chunks = Counter()
    relation_pages = Counter()
    relation_chunks = Counter()
    depth_histogram = Counter()
    ambiguous_pages = []
    unmapped_pages = []
    pages_mapped = 0
    pages_unmapped = 0
    chunks_mapped = 0
    chunks_unmapped = 0

    for entry in pages:
        doc_path = args.corpus_dir / entry["local_filename"]
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
        result = classify_page(entry["canonical_title"], doc["wikitext"])

        status_counter[result.status] += 1
        if result.reason:
            reason_counter[result.reason] += 1

        if result.status == "rejected":
            page_records.append(
                {
                    "page_id": entry["page_id"],
                    "canonical_title": entry["canonical_title"],
                    "wikibooks_page_id": entry["wikibooks_page_id"],
                    "wikibooks_revision_id": entry["wikibooks_revision_id"],
                    "source_url": entry["source_url"],
                    "status": result.status,
                    "reason": result.reason,
                }
            )
            continue

        page_sections = []
        for section in result.sections:
            intent_counter[section.intent] += 1
            page_sections.append(
                {
                    "section_title": section.title,
                    "section_index": section.section_index,
                    "intent": section.intent,
                    "side": section.side,
                    "tags": list(section.tags),
                    "difficulty": section.difficulty,
                    "is_history": section.is_history,
                    "is_misc": section.is_misc,
                }
            )

        page_records.append(
            {
                "page_id": entry["page_id"],
                "canonical_title": entry["canonical_title"],
                "wikibooks_page_id": entry["wikibooks_page_id"],
                "wikibooks_revision_id": entry["wikibooks_revision_id"],
                "source_url": entry["source_url"],
                "license_or_terms": LICENSE,
                "status": result.status,
                "reason": None,
                "sections": page_sections,
                "mapping": _page_mapping(entry, result, tree),
            }
        )

        for section in result.sections:
            dup_sections.append((entry["page_id"], section.text, section.title))

        chunks = _chunk_page(entry, doc, result, tree)
        chunk_records.extend(chunks)

    exact_groups, near_duplicates = find_duplicates(dup_sections)

    for chunk in chunk_records:
        if chunk["mapping_status"] == "mapped":
            chunks_mapped += 1
            depth_histogram[chunk["mapping_depth_delta"]] += 1
        else:
            chunks_unmapped += 1
        mapping_chunks[chunk["mapping_confidence"]] += 1
        if chunk["mapping_relation"]:
            relation_chunks[chunk["mapping_relation"]] += 1

    for page in page_records:
        mapping = page.get("mapping")
        if mapping is None:
            continue
        mapping_pages[mapping["confidence"]] += 1
        if mapping["relation"]:
            relation_pages[mapping["relation"]] += 1
        if mapping["status"] == "mapped":
            pages_mapped += 1
        else:
            pages_unmapped += 1
            unmapped_pages.append(
                {
                    "page_id": page["page_id"],
                    "canonical_title": page["canonical_title"],
                    "reason": mapping["reason"],
                }
            )
        if mapping["ambiguous"]:
            ambiguous_pages.append(
                {"page_id": page["page_id"], "canonical_title": page["canonical_title"]}
            )

    byte_lengths = [utf8_length(c["text"]) for c in chunk_records]
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cleaner_version": 2,
        "source": "wikibooks-chess-opening-theory",
        "license_or_terms": LICENSE,
        "counts": {
            "pages_total": len(pages),
            "pages_by_status": dict(status_counter),
            "pages_by_reason": dict(reason_counter),
            "accepted_pages": status_counter.get("accepted", 0),
            "rejected_pages": status_counter.get("rejected", 0),
            "chunks": len(chunk_records),
            "sections_by_intent": dict(intent_counter),
            "exact_duplicate_groups": len(exact_groups),
            "near_duplicates": len(near_duplicates),
            "byte_budget_max": MAX_BYTES,
            "byte_budget_max_chunk": max(byte_lengths) if byte_lengths else 0,
            "byte_budget_violations": sum(1 for n in byte_lengths if n > MAX_BYTES),
            "opening_mapping_status": "complete",
        },
        "opening_mapping": {
            "pages_mapped": pages_mapped,
            "pages_unmapped": pages_unmapped,
            "chunks_mapped": chunks_mapped,
            "chunks_unmapped": chunks_unmapped,
            "pages_by_confidence": dict(mapping_pages),
            "chunks_by_confidence": dict(mapping_chunks),
            "pages_by_relation": dict(relation_pages),
            "chunks_by_relation": dict(relation_chunks),
            "chunk_depth_delta_histogram": dict(sorted(depth_histogram.items())),
            "ambiguous_pages": ambiguous_pages,
            "unmapped_pages": unmapped_pages,
        },
        "exact_duplicate_groups": [
            [{"page_id": ref["page_id"], "section_title": ref["section_title"]} for ref in group]
            for group in exact_groups
        ],
        "near_duplicates": near_duplicates,
    }

    (args.output_dir / "pages.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in page_records) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in chunk_records) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "quality-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    counts = report["counts"]
    mapping = report["opening_mapping"]
    print(f"pages   : {counts['pages_total']} total -> {counts['accepted_pages']} accepted, {counts['rejected_pages']} rejected")
    print(f"reasons : {dict(reason_counter)}")
    print(f"chunks  : {counts['chunks']}")
    print(f"intent  : {dict(intent_counter)}")
    print(f"dups    : {counts['exact_duplicate_groups']} exact groups, {counts['near_duplicates']} near")
    print(f"mapping : {mapping['pages_mapped']} pages mapped / {mapping['pages_unmapped']} unmapped; "
          f"{mapping['chunks_mapped']} chunks mapped / {mapping['chunks_unmapped']} unmapped")
    print(f"confid  : {dict(mapping_pages)}")
    print(f"relation: {dict(relation_pages)}")
    print(f"depth   : {dict(sorted(depth_histogram.items()))}")
    print(f"report  : {args.output_dir / 'quality-report.json'}")
    return 0


def _page_mapping(entry: dict, result, tree) -> dict:
    return map_page(entry["canonical_title"], tree).page_fields()


def _chunk_page(entry: dict, doc: dict, result, tree) -> list[dict]:
    page_mapping = map_page(entry["canonical_title"], tree)
    mappings_by_section = _section_mappings(page_mapping, result.sections, tree)
    sections = tuple(
        ChunkSection(
            title=section.title,
            text=section.text,
            intent=section.intent,
            side=section.side,
            is_history=section.is_history,
            is_misc=section.is_misc,
        )
        for section in result.sections
        if section.text.strip()
    )
    source = ChunkSource(
        source="wikibooks-chess-opening-theory",
        page_title=result.title,
        page_text=result.page_text,
        source_url=entry["source_url"],
        license_or_terms=LICENSE,
        sections=sections,
    )
    records = []
    for chunk in chunk_source(source, granularity="section", max_bytes=MAX_BYTES):
        record = {
            "id": chunk.id,
            "text": chunk.text,
            "source": chunk.source,
            "page_id": chunk.page_id,
            "canonical_title": chunk.canonical_title,
            "section_title": chunk.section_title,
            "section_index": chunk.section_index,
            "part_index": chunk.part_index,
            "intent": chunk.intent,
            "side": chunk.side,
            "is_history": chunk.is_history,
            "is_misc": chunk.is_misc,
            "source_url": chunk.source_url,
            "license_or_terms": chunk.license_or_terms,
            "wikibooks_revision_id": entry["wikibooks_revision_id"],
            "difficulty": None,
            "tags": [],
            "created_at": chunk.created_at,
        }
        if chunk.section_index is not None:
            record.update(mappings_by_section[chunk.section_index].chunk_fields())
        records.append(record)
    return records


def _section_mappings(page_mapping, sections, tree) -> list:
    mappings = []
    for section in sections:
        if not section.text.strip():
            continue
        refined = refine_section(page_mapping, section.title, tree)
        mappings.append(refined or page_mapping)
    return mappings


if __name__ == "__main__":
    raise SystemExit(main())
