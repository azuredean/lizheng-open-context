#!/usr/bin/env python3
"""Dependency-free lexical search for the open context repository."""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
HAN_RUN = re.compile(r"[\u3400-\u9fff]+")
WORD = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_+.-]+")


@dataclass
class Document:
    id: str
    source_id: str
    title: str
    section: str
    source_type: str
    source_url: str
    published_at: str
    text: str
    path: str
    content_status: str = "current"


def parse_scalar(value: str):
    value = value.strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def chunk_markdown(body: str, source_type: str, target_chars: int = 3200) -> list[tuple[str, str]]:
    """Split long sources without losing headings or timestamp links."""
    if source_type == "video-transcript":
        sections = [body]
    else:
        sections = [part for part in re.split(r"(?m)(?=^##\s+)", body) if part.strip()]
    chunks: list[tuple[str, str]] = []
    for section_text in sections:
        heading_match = re.search(r"(?m)^#{2,6}\s+(.+?)\s*$", section_text)
        section_name = heading_match.group(1).strip() if heading_match else ""
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section_text) if part.strip()]
        current: list[str] = []
        current_size = 0
        for paragraph in paragraphs:
            if current and current_size + len(paragraph) > target_chars:
                chunks.append((section_name, "\n\n".join(current)))
                current = current[-1:] if source_type == "video-transcript" else []
                current_size = sum(len(part) for part in current)
            current.append(paragraph)
            current_size += len(paragraph)
        if current:
            chunks.append((section_name, "\n\n".join(current)))
    return chunks or [("", body)]


def parse_markdown(path: Path) -> list[Document]:
    raw = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(raw)
    meta: dict[str, object] = {}
    body = raw
    if match:
        body = raw[match.end() :]
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = parse_scalar(value)
    source_id = str(meta.get("id") or path.stem)
    source_type = str(meta.get("source_type") or "context")
    source_url = str(meta.get("source_url") or "")
    documents = []
    for index, (section, text) in enumerate(chunk_markdown(body, source_type), 1):
        timestamp_link = re.search(
            r"\[\d{2}:\d{2}:\d{2}\]\((https://www\.youtube\.com/watch\?v=[^)]+)\)",
            text,
        )
        documents.append(
            Document(
                id=f"{source_id}#chunk-{index}",
                source_id=source_id,
                title=str(meta.get("title") or path.stem),
                section=section,
                source_type=source_type,
                source_url=timestamp_link.group(1) if timestamp_link else source_url,
                published_at=str(meta.get("published_at") or meta.get("snapshot_at") or ""),
                text=text,
                path=str(path.relative_to(ROOT)),
                content_status=str(meta.get("content_status") or "current"),
            )
        )
    return documents


def load_documents() -> list[Document]:
    docs: list[Document] = []
    full_ids: set[str] = set()
    for pattern in (
        "context/*.md",
        "corpus/community-posts/*.md",
        "corpus/community-comments/*.md",
        "corpus/videos/*.md",
    ):
        for path in sorted(ROOT.glob(pattern)):
            parsed = parse_markdown(path)
            docs.extend(parsed)
            full_ids.update(doc.source_id for doc in parsed)
    for catalog_name, source_type in (
        ("knowledge-bank.jsonl", "knowledge-bank-catalog"),
        ("videos.jsonl", "video-catalog"),
    ):
        path = ROOT / "catalog" / catalog_name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["id"] in full_ids:
                continue
            docs.append(
                Document(
                    id=row["id"],
                    source_id=row["id"],
                    title=row["title"],
                    section="",
                    source_type=source_type,
                    source_url=row.get("url", ""),
                    published_at=row.get("published_at") or "",
                    text=" ".join(row.get("guest_names") or []),
                    path=str(path.relative_to(ROOT)),
                    content_status=str(row.get("content_status") or "current"),
                )
            )
    return docs


def query_terms(query: str) -> list[str]:
    lowered = query.lower().strip()
    terms = set(WORD.findall(lowered))
    for run in HAN_RUN.findall(lowered):
        if len(run) == 1:
            terms.add(run)
        else:
            terms.update(run[i : i + 2] for i in range(len(run) - 1))
    return sorted((term for term in terms if term), key=len, reverse=True)


def score(
    doc: Document,
    query: str,
    terms: list[str],
    document_frequency: dict[str, int],
    document_count: int,
    average_length: float,
) -> float:
    title = (doc.title + "\n" + doc.section).lower()
    body = re.sub(r"\]\([^)]+\)", "]", doc.text).lower()
    query_lower = query.lower().strip()
    value = 0.0
    if query_lower and query_lower in title:
        value += 40
    if query_lower and query_lower in body:
        value += 10
    length = max(1, len(body))
    k1 = 1.35
    b = 0.78
    for term in terms:
        df = document_frequency.get(term, 0)
        inverse_frequency = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
        if term in title:
            value += inverse_frequency * 5.5
        frequency = body.count(term)
        if frequency:
            normalized = frequency * (k1 + 1) / (
                frequency + k1 * (1 - b + b * length / average_length)
            )
            value += inverse_frequency * normalized
    source_weight = {
        "context": 1.28,
        "book-framework": 1.24,
        "knowledge-bank": 1.14,
        "community-post": 1.04,
        "community-comment": 0.82,
        "video-transcript": 1.0,
        "knowledge-bank-catalog": 0.72,
        "video-catalog": 0.68,
    }.get(doc.source_type, 1.0)
    status_weight = {"current": 1.0, "archived": 0.55, "test": 0.2}.get(
        doc.content_status, 1.0
    )
    return value * source_weight * status_weight


def snippet(doc: Document, query: str, terms: list[str], width: int = 220) -> str:
    plain = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1 (\2)", doc.text)
    plain = re.sub(r"[#>*`]", "", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    lowered = plain.lower()
    needles = [query.lower().strip(), *terms]
    positions = [lowered.find(term) for term in needles if term and lowered.find(term) >= 0]
    start = max(0, (min(positions) if positions else 0) - width // 3)
    end = min(len(plain), start + width)
    prefix = "…" if start else ""
    suffix = "…" if end < len(plain) else ""
    return prefix + plain[start:end] + suffix


def type_matches(doc: Document, requested: str) -> bool:
    if requested == "all":
        return True
    if requested == "video":
        return doc.source_type in {"video-transcript", "video-catalog"}
    if requested == "knowledge-bank":
        return doc.source_type in {"knowledge-bank", "knowledge-bank-catalog"}
    if requested == "community":
        return doc.source_type in {"knowledge-bank", "community-post", "community-comment"}
    if requested == "comment":
        return doc.source_type == "community-comment"
    if requested == "context":
        return doc.source_type in {"context", "book-framework"}
    return doc.source_type == requested


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument(
        "--type",
        choices=["all", "context", "knowledge-bank", "community", "comment", "video"],
        default="all",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    terms = query_terms(args.query)
    documents = [doc for doc in load_documents() if type_matches(doc, args.type)]
    document_count = max(1, len(documents))
    average_length = sum(max(1, len(doc.text)) for doc in documents) / document_count
    document_frequency = {
        term: sum(term in (doc.title + "\n" + doc.text).lower() for doc in documents)
        for term in terms
    }
    ranked = []
    for doc in documents:
        value = score(
            doc,
            args.query,
            terms,
            document_frequency,
            document_count,
            average_length,
        )
        if value > 0:
            ranked.append((value, doc))
    ranked.sort(key=lambda item: (-item[0], item[1].published_at, item[1].title))
    results = []
    seen_sources: set[str] = set()
    for value, doc in ranked:
        if doc.source_id in seen_sources:
            continue
        seen_sources.add(doc.source_id)
        results.append(
            {
                "score": round(value, 1),
                "title": doc.title,
                "section": doc.section,
                "source_type": doc.source_type,
                "published_at": doc.published_at,
                "url": doc.source_url,
                "path": doc.path,
                "content_status": doc.content_status,
                "snippet": snippet(doc, args.query, terms),
            }
        )
        if len(results) >= max(1, args.top):
            break
    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    if not results:
        print("No matching public sources found.")
        return
    for index, result in enumerate(results, 1):
        print(f"{index}. {result['title']}  [{result['source_type']}]  score={result['score']}")
        if result["section"]:
            print(f"   section: {result['section']}")
        if result["published_at"]:
            print(f"   date: {result['published_at'][:10]}")
        if result["url"]:
            print(f"   source: {result['url']}")
        print(f"   {result['snippet']}")


if __name__ == "__main__":
    main()
