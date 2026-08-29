#!/usr/bin/env python3
"""Build the public corpus from an already-sanitized Circle export and local media manifest.

The exporter deliberately needs explicit source paths. It never reads private context,
messages, descriptions, comments, credentials, or raw media.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
YUZHENG_NAME = "YZ｜立正"
MIXED_SPEAKER_HINT = re.compile(
    r"(?:访谈|专访|采访|圆桌|对谈|对话|聊天|闲扯|实况|播客|podcast|interview|"
    r"和.{1,18}聊|与.{1,18}聊|课代表.{0,8}×|鸭哥演示|冯老师品酒课|master sommelier)",
    re.IGNORECASE,
)
TIMECODE = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})"
)


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def front_matter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = str(value)
        elif isinstance(value, list):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = yaml_string(str(value))
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def reset_generated_dir(path: Path) -> None:
    resolved = path.resolve()
    resolved.relative_to(ROOT.resolve())
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


class MarkdownHTMLParser(HTMLParser):
    """Small, dependency-free converter for Circle's published article HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self.list_stack: list[str] = []
        self.ordered_index: list[int] = []
        self.in_pre = False
        self.blockquote_depth = 0
        self.list_item_depth = 0

    def emit(self, value: str) -> None:
        self.parts.append(value)

    def newline(self, count: int = 1) -> None:
        current = "".join(self.parts)
        trailing = len(current) - len(current.rstrip("\n"))
        if trailing < count:
            self.emit("\n" * (count - trailing))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k: v or "" for k, v in attrs}
        if tag == "p":
            if self.list_item_depth:
                return
            if self.blockquote_depth:
                self.newline(1)
                self.emit("> ")
            else:
                self.newline(2)
        elif tag in {"div", "section"}:
            self.newline(2)
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.newline(2)
            self.emit("#" * int(tag[1]) + " ")
        elif tag == "br":
            self.newline(1)
        elif tag == "hr":
            self.newline(2)
            self.emit("---")
            self.newline(2)
        elif tag == "blockquote":
            self.newline(2)
            self.blockquote_depth += 1
        elif tag in {"strong", "b"}:
            self.emit("**")
        elif tag in {"em", "i"}:
            self.emit("*")
        elif tag == "code" and not self.in_pre:
            self.emit("`")
        elif tag == "pre":
            self.newline(2)
            self.emit("```\n")
            self.in_pre = True
        elif tag == "a":
            self.emit("[")
            self.links.append(attrs_dict.get("href", ""))
        elif tag in {"ul", "ol"}:
            self.list_stack.append(tag)
            if tag == "ol":
                self.ordered_index.append(0)
            self.newline(1)
        elif tag == "li":
            self.newline(1)
            self.list_item_depth += 1
            indent = "  " * max(0, len(self.list_stack) - 1)
            if self.list_stack and self.list_stack[-1] == "ol":
                self.ordered_index[-1] += 1
                marker = f"{self.ordered_index[-1]}. "
            else:
                marker = "- "
            self.emit(indent + marker)
        elif tag == "img":
            alt = attrs_dict.get("alt", "").strip()
            if alt:
                self.emit(f"[图片：{alt}]")

    def handle_endtag(self, tag: str) -> None:
        if tag == "p":
            if not self.list_item_depth:
                self.newline(1 if self.blockquote_depth else 2)
        elif tag in {"div", "section"} or tag.startswith("h"):
            self.newline(2)
        elif tag == "blockquote":
            self.blockquote_depth = max(0, self.blockquote_depth - 1)
            self.newline(2)
        elif tag == "li":
            self.list_item_depth = max(0, self.list_item_depth - 1)
        elif tag in {"strong", "b"}:
            self.emit("**")
        elif tag in {"em", "i"}:
            self.emit("*")
        elif tag == "code" and not self.in_pre:
            self.emit("`")
        elif tag == "pre":
            self.emit("\n```")
            self.newline(2)
            self.in_pre = False
        elif tag == "a":
            href = self.links.pop() if self.links else ""
            self.emit(f"]({href})" if href else "]")
        elif tag in {"ul", "ol"}:
            if self.list_stack:
                ended = self.list_stack.pop()
                if ended == "ol" and self.ordered_index:
                    self.ordered_index.pop()
            self.newline(2)

    def handle_data(self, data: str) -> None:
        if self.in_pre:
            self.emit(data)
            return
        cleaned = re.sub(r"[ \t\r\f\v]+", " ", data)
        self.emit(cleaned)

    def markdown(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"\n[ \t]+\n", "\n\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" +\n", "\n", text)
        return text.strip()


def html_to_markdown(value: str) -> str:
    parser = MarkdownHTMLParser()
    parser.feed(value)
    parser.close()
    return parser.markdown()


def choose_transcript_path(folder: Path, status: str | None) -> Path | None:
    candidates: list[Path] = []
    candidates.extend(folder.glob("*.srt"))
    candidates.extend(folder.glob("*.vtt"))
    for process_dir in sorted(folder.glob("*_process")):
        if process_dir.is_dir():
            candidates.extend(process_dir.glob("*.srt"))
            candidates.extend(process_dir.glob("*.vtt"))
    usable = sorted(
        {path.resolve() for path in candidates if path.is_file() and path.stat().st_size > 20},
        key=str,
    )
    if not usable:
        return None

    def score(path: Path) -> tuple[int, str]:
        name = path.name.lower()
        if name.endswith(".corrected.srt") or name.endswith(".final.srt"):
            priority = 0
        elif status == "human" and any(
            marker in name for marker in (".zh-hans.", ".zh-hant.", ".zh.", ".en.")
        ):
            priority = 1
        elif ".qwen." in name:
            priority = 4
        elif name.endswith(".srt"):
            priority = 2
        elif name.endswith(".vtt"):
            priority = 3
        else:
            priority = 5
        return priority, str(path)

    return min(usable, key=score)


def timestamp_seconds(value: str) -> int:
    match = TIMECODE.search(value)
    if not match:
        return 0
    return int(match["h"]) * 3600 + int(match["m"]) * 60 + int(match["s"])


def display_timestamp(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_timed_transcript(path: Path) -> list[tuple[int, str]]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n").replace("\r", "\n"))
    cues: list[tuple[int, str]] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        start = timestamp_seconds(lines[timing_index].split("-->", 1)[0])
        text_lines = lines[timing_index + 1 :]
        text_value = " ".join(text_lines)
        text_value = re.sub(r"<[^>]+>", "", text_value)
        text_value = html.unescape(text_value)
        text_value = re.sub(r"\s+", " ", text_value).strip()
        if not text_value:
            continue
        if cues and text_value == cues[-1][1]:
            continue
        cues.append((start, text_value))
    return cues


def article_filename(record: dict[str, Any]) -> str:
    date = (record.get("published_at") or "undated")[:10].replace("-", "")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", record.get("slug") or str(record["id"]))
    return f"{date}-{slug}-{record['id']}.md"


def export_knowledge_bank(cache_path: Path, snapshot_at: str) -> dict[str, int]:
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    records = payload["records"]
    corpus_dir = ROOT / "corpus" / "knowledge-bank"
    catalog_path = ROOT / "catalog" / "knowledge-bank.jsonl"
    reset_generated_dir(corpus_dir)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_rows: list[dict[str, Any]] = []
    full_text_count = 0
    for record in sorted(records, key=lambda item: item.get("published_at") or ""):
        is_yuzheng = bool(record.get("is_yuzheng")) and record.get("author") == YUZHENG_NAME
        corpus_path: str | None = None
        if is_yuzheng:
            body = html_to_markdown(record.get("body_html") or "")
            if body:
                filename = article_filename(record)
                target = corpus_dir / filename
                fields = {
                    "id": f"circle-{record['id']}",
                    "title": record["title"],
                    "author": "Yuzheng Sun",
                    "source_type": "knowledge-bank",
                    "source_url": record["url"],
                    "published_at": record.get("published_at"),
                    "updated_at": record.get("updated_at"),
                    "snapshot_at": snapshot_at,
                    "rights_scope": "first-party",
                    "license": "CC-BY-4.0",
                    "third_party_exclusions": True,
                }
                source_note = (
                    f"\n> 原文：[{record['title']}]({record['url']}) · "
                    f"发布于 {(record.get('published_at') or '日期未知')[:10]}。"
                    "许可不覆盖文中的第三方引文、访谈发言、链接与商标。\n\n"
                )
                target.write_text(front_matter(fields) + source_note + body + "\n", encoding="utf-8")
                corpus_path = str(target.relative_to(ROOT))
                full_text_count += 1
        catalog_rows.append(
            {
                "id": f"circle-{record['id']}",
                "title": record["title"],
                "author": "Yuzheng Sun" if is_yuzheng else record.get("author"),
                "url": record["url"],
                "published_at": record.get("published_at"),
                "updated_at": record.get("updated_at"),
                "rights_scope": "first-party" if is_yuzheng else "metadata-only",
                "full_text_included": bool(corpus_path),
                "corpus_path": corpus_path,
            }
        )
    with catalog_path.open("w", encoding="utf-8") as handle:
        for row in catalog_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"catalog": len(catalog_rows), "full_text": full_text_count}


def load_guests(path: Path) -> tuple[set[str], dict[str, list[str]]]:
    guest_ids: set[str] = set()
    names: dict[str, list[str]] = {}
    for guest in json.loads(path.read_text(encoding="utf-8")):
        guest_name = guest.get("guest_name") or guest.get("guest_en_name") or "嘉宾"
        for video_id in guest.get("all_video_ids") or []:
            guest_ids.add(video_id)
            names.setdefault(video_id, []).append(guest_name)
    return guest_ids, names


def load_id_allowlist(path: Path) -> set[str]:
    """Load an explicit, reviewed set of video IDs; new videos default to metadata-only."""
    ids: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
            raise ValueError(f"{path.name}:{number}: invalid YouTube video ID {value!r}")
        ids.append(value)
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: duplicate video IDs")
    return set(ids)


def classify_video_rights(
    video_id: str,
    title: str,
    guest_ids: set[str],
    rights_overrides: dict[str, str],
    transcript_allowlist: set[str],
) -> dict[str, str | list[str]]:
    exclusion_reasons: list[str] = []
    if video_id in guest_ids:
        exclusion_reasons.append("known-guest-index")
    if MIXED_SPEAKER_HINT.search(title):
        exclusion_reasons.append("mixed-speaker-title")
    if video_id in rights_overrides:
        exclusion_reasons.append(f"manual-review: {rights_overrides[video_id]}")

    if video_id in transcript_allowlist and exclusion_reasons:
        raise ValueError(
            f"{video_id}: transcript allowlist conflicts with mixed-speaker evidence: "
            + "; ".join(exclusion_reasons)
        )
    if exclusion_reasons:
        return {
            "rights_scope": "mixed-speakers",
            "speaker_classification": "mixed-speakers",
            "review_status": "excluded",
            "rights_reasons": exclusion_reasons,
        }
    if video_id in transcript_allowlist:
        return {
            "rights_scope": "first-party",
            "speaker_classification": "solo-yuzheng",
            "review_status": "approved",
            "rights_reasons": ["explicit-v1-transcript-allowlist"],
        }
    return {
        "rights_scope": "metadata-only",
        "speaker_classification": "unreviewed",
        "review_status": "unreviewed",
        "rights_reasons": ["not-in-transcript-allowlist"],
    }


def eligible_video(record: dict[str, Any]) -> bool:
    return (
        record.get("youtube_privacy") == "public"
        and record.get("content_class") == "normal_video"
        and record.get("podcast_policy") == "ready_public_normal"
        and record.get("local_status") == "ok"
    )


def export_videos(
    channel_root: Path,
    snapshot_at: str,
    rights_overrides: dict[str, str],
    transcript_allowlist: set[str],
) -> dict[str, int]:
    manifest_path = channel_root / "logs" / "library_manifest" / "library_manifest.json"
    guest_path = channel_root / "guests.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    guest_ids, guest_names = load_guests(guest_path)
    records = [record for record in manifest["records"] if eligible_video(record)]
    eligible_ids = {record["video_id"] for record in records}
    stale_allowlist_ids = sorted(transcript_allowlist - eligible_ids)
    if stale_allowlist_ids:
        raise ValueError(
            "Transcript allowlist contains videos outside the eligible public snapshot: "
            + ", ".join(stale_allowlist_ids)
        )
    corpus_dir = ROOT / "corpus" / "videos"
    catalog_path = ROOT / "catalog" / "videos.jsonl"
    reset_generated_dir(corpus_dir)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_rows: list[dict[str, Any]] = []
    transcript_available = 0
    transcript_included = 0
    mixed_speaker_count = 0
    unreviewed_count = 0

    for record in sorted(records, key=lambda item: item.get("youtube_published_at") or ""):
        video_id = record["video_id"]
        title = record["title"]
        url = f"https://www.youtube.com/watch?v={video_id}"
        folder = (channel_root / record["folder"]).resolve()
        folder.relative_to(channel_root.resolve())
        transcript_path = choose_transcript_path(folder, record.get("transcript_status"))
        has_transcript = transcript_path is not None
        if has_transcript:
            transcript_available += 1
        classification = classify_video_rights(
            video_id, title, guest_ids, rights_overrides, transcript_allowlist
        )
        rights_scope = str(classification["rights_scope"])
        rights_reasons = list(classification["rights_reasons"])
        if rights_scope == "mixed-speakers":
            mixed_speaker_count += 1
        elif rights_scope == "metadata-only":
            unreviewed_count += 1
        corpus_path: str | None = None
        cue_count = 0
        if has_transcript and rights_scope == "first-party":
            cues = parse_timed_transcript(transcript_path)
            cue_count = len(cues)
            if cues:
                date = (record.get("youtube_published_at") or record.get("upload_date") or "undated")[:10]
                safe_date = date.replace("-", "")
                target = corpus_dir / f"{safe_date}-{video_id}.md"
                fields = {
                    "id": f"youtube-{video_id}",
                    "title": title,
                    "author": "Yuzheng Sun",
                    "source_type": "video-transcript",
                    "source_url": url,
                    "published_at": record.get("youtube_published_at"),
                    "snapshot_at": snapshot_at,
                    "rights_scope": "first-party",
                    "speaker_classification": classification["speaker_classification"],
                    "review_status": classification["review_status"],
                    "license": "CC-BY-4.0",
                    "third_party_exclusions": True,
                    "transcript_status": record.get("transcript_status"),
                }
                lines = [front_matter(fields), f"# {title}\n"]
                lines.append(
                    f"> [观看原视频]({url}) · 字幕状态：`{record.get('transcript_status')}`。"
                    "字幕可能有转写错误，请以原视频为准。许可不覆盖发言中引用的第三方材料。\n"
                )
                for seconds, cue in cues:
                    time_url = f"{url}&t={seconds}s"
                    lines.append(f"[{display_timestamp(seconds)}]({time_url}) {cue}\n")
                target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
                corpus_path = str(target.relative_to(ROOT))
                transcript_included += 1
        catalog_rows.append(
            {
                "id": f"youtube-{video_id}",
                "video_id": video_id,
                "title": title,
                "url": url,
                "published_at": record.get("youtube_published_at"),
                "transcript_status": record.get("transcript_status"),
                "transcript_available": has_transcript,
                "transcript_included": bool(corpus_path),
                "cue_count": cue_count,
                "rights_scope": rights_scope,
                "speaker_classification": classification["speaker_classification"],
                "review_status": classification["review_status"],
                "rights_reason": "; ".join(rights_reasons),
                "guest_names": sorted(set(guest_names.get(video_id, []))),
                "corpus_path": corpus_path,
            }
        )
    with catalog_path.open("w", encoding="utf-8") as handle:
        for row in catalog_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "catalog": len(catalog_rows),
        "transcript_available": transcript_available,
        "transcript_included": transcript_included,
        "mixed_speaker_metadata_only": mixed_speaker_count,
        "unreviewed_metadata_only": unreviewed_count,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--channel-root",
        type=Path,
        required=True,
        help="Path to the local kedaibiao-channel repository",
    )
    parser.add_argument(
        "--knowledge-cache",
        type=Path,
        default=ROOT / ".source-cache" / "knowledge-bank.json",
        help="Sanitized public Circle export (private fields must already be removed)",
    )
    parser.add_argument("--snapshot-at", default="2026-08-29")
    parser.add_argument(
        "--rights-overrides",
        type=Path,
        default=ROOT / "config" / "video-rights-overrides.json",
        help="Reviewed video IDs that must remain metadata-only",
    )
    parser.add_argument(
        "--transcript-allowlist",
        type=Path,
        default=ROOT / "config" / "video-transcript-allowlist.txt",
        help="Explicitly reviewed solo-Yuzheng video IDs allowed to export full transcripts",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    channel_root = args.channel_root.expanduser().resolve()
    cache_path = args.knowledge_cache.expanduser().resolve()
    rights_path = args.rights_overrides.expanduser().resolve()
    allowlist_path = args.transcript_allowlist.expanduser().resolve()
    if not cache_path.is_file():
        raise SystemExit(f"Missing sanitized Knowledge Bank cache: {cache_path}")
    if not (channel_root / "logs" / "library_manifest" / "library_manifest.json").is_file():
        raise SystemExit(f"Not a kedaibiao-channel source root: {channel_root}")
    if not rights_path.is_file():
        raise SystemExit(f"Missing video rights override file: {rights_path}")
    if not allowlist_path.is_file():
        raise SystemExit(f"Missing transcript allowlist file: {allowlist_path}")
    rights_overrides = json.loads(rights_path.read_text(encoding="utf-8"))
    transcript_allowlist = load_id_allowlist(allowlist_path)
    knowledge = export_knowledge_bank(cache_path, args.snapshot_at)
    videos = export_videos(
        channel_root, args.snapshot_at, rights_overrides, transcript_allowlist
    )
    print(json.dumps({"knowledge_bank": knowledge, "videos": videos}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
