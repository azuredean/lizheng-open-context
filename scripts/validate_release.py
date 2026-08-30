#!/usr/bin/env python3
"""Fail closed on common privacy, provenance, rights, and release-integrity mistakes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release-manifest.json"
SCAN_DIRS = (
    ROOT / "context",
    ROOT / "corpus",
    ROOT / "catalog",
    ROOT / "config",
    ROOT / "docs",
    ROOT / "evals",
    ROOT / "examples",
)
SCAN_ROOT_FILES = (
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "LICENSE-CONTENT.md",
)
SENSITIVE_PATTERNS = {
    "email address": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "mainland phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "macOS absolute path": re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    "Windows absolute path": re.compile(r"[A-Za-z]:\\\\Users\\\\"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "GitHub token": re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),
    "generic secret assignment": re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*['\"][^'\"]{8,}"
    ),
}
FORBIDDEN_FIELDS = ('"user_email"', '"user_id"', '"community_id"')
URL_PATTERN = re.compile(r"https?://[^\s)\]>'\"]+", re.IGNORECASE)
BARE_DOMAIN_PATTERN = re.compile(
    r"(?<![@\w])(?:[A-Za-z0-9-]+\.)+(?:com|org|net|io|ai|co|cn)(?:/[^\s]*)?",
    re.IGNORECASE,
)
COMMENT_SENSITIVE_PATTERN = re.compile(
    r"(?:therapist|治疗师|心理咨询|抑郁|sponsor(?:ship)?|月收入|工资|薪资|报酬|"
    r"财务状况|PERM|EB-?1A|绿卡|被裁|裁员|未成年|\b17\s*岁|生病|离世|去世|"
    r"戒烟|伴侣|老婆|老公|男朋友|女朋友|私下|社群不赚钱|接管.{0,12}运营|"
    r"退款|refund|老学员|新学员|购买|优惠|折扣|报名|名额|课程|qualify|"
    r"付款|price|价格|预算|订单|客服|发票|上课|开课|lifetime|"
    r"\bcourse\b|\bmaven\b|\bcohort\b|self[- ]paced|"
    r"每月\s*\$?\s*\d+|\$\s*\d+.{0,12}(?:month|月)|"
    r"(?:跟|和|与).{0,12}(?:聊完|聊天|交流))",
    re.IGNORECASE,
)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.relative_to(ROOT)}:{number}: invalid JSON: {exc}") from exc
    return rows


def read_json_object_without_duplicate_keys(path: Path) -> dict:
    def pairs_hook(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path.relative_to(ROOT)}: duplicate key {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs_hook)


def read_allowlist(path: Path) -> set[str]:
    values = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(values) != len(set(values)):
        raise ValueError(f"{path.relative_to(ROOT)}: duplicate video IDs")
    return set(values)


def public_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if relative == Path("release-manifest.json"):
            continue
        if any(part in {".git", ".source-cache", "__pycache__"} for part in relative.parts):
            continue
        files.append(path)
    return sorted(files, key=lambda path: str(path.relative_to(ROOT)))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_sensitive_data(errors: list[str]) -> None:
    scan_files = [path for path in SCAN_ROOT_FILES if path.is_file()]
    for directory in SCAN_DIRS:
        if directory.exists():
            scan_files.extend(path for path in directory.rglob("*") if path.is_file())
    for path in scan_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in SENSITIVE_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{path.relative_to(ROOT)}: possible {label}")
        if path.suffix == ".jsonl":
            for field in FORBIDDEN_FIELDS:
                if field in text:
                    errors.append(f"{path.relative_to(ROOT)}: forbidden private field {field}")


def validate_internal_links(errors: list[str]) -> None:
    link_pattern = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
    for path in public_files():
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for raw_target in link_pattern.findall(text):
            target = raw_target.strip().split("#", 1)[0]
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue
            decoded = unquote(target)
            resolved = (path.parent / decoded).resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                errors.append(f"{path.relative_to(ROOT)}: link escapes repository: {raw_target}")
                continue
            if not resolved.exists():
                errors.append(f"{path.relative_to(ROOT)}: broken internal link: {raw_target}")


def validate_rights(errors: list[str]) -> dict[str, int]:
    kb_catalog_path = ROOT / "catalog" / "knowledge-bank.jsonl"
    community_posts_catalog_path = ROOT / "catalog" / "community-posts.jsonl"
    community_comments_catalog_path = ROOT / "catalog" / "community-comments.jsonl"
    video_catalog_path = ROOT / "catalog" / "videos.jsonl"
    if not kb_catalog_path.is_file():
        errors.append("catalog/knowledge-bank.jsonl is missing")
        kb_rows = []
    else:
        kb_rows = read_jsonl(kb_catalog_path)
    if not community_posts_catalog_path.is_file():
        errors.append("catalog/community-posts.jsonl is missing")
        community_post_rows = []
    else:
        community_post_rows = read_jsonl(community_posts_catalog_path)
    if not community_comments_catalog_path.is_file():
        errors.append("catalog/community-comments.jsonl is missing")
        community_comment_rows = []
    else:
        community_comment_rows = read_jsonl(community_comments_catalog_path)
    if not video_catalog_path.is_file():
        errors.append("catalog/videos.jsonl is missing")
        video_rows = []
    else:
        video_rows = read_jsonl(video_catalog_path)

    comment_policy_path = ROOT / "config" / "community-comment-policy.json"
    if not comment_policy_path.is_file():
        errors.append("config/community-comment-policy.json is missing")
        comment_policy = {}
    else:
        comment_policy = read_json_object_without_duplicate_keys(comment_policy_path)

    allowlist_path = ROOT / "config" / "video-transcript-allowlist.txt"
    overrides_path = ROOT / "config" / "video-rights-overrides.json"
    if not allowlist_path.is_file() or not overrides_path.is_file():
        errors.append("video rights config is missing")
        transcript_allowlist: set[str] = set()
        rights_overrides: dict = {}
    else:
        transcript_allowlist = read_allowlist(allowlist_path)
        rights_overrides = read_json_object_without_duplicate_keys(overrides_path)

    for row in kb_rows:
        if row.get("full_text_included") and (
            row.get("author") != "Yuzheng Sun" or row.get("rights_scope") != "first-party"
        ):
            errors.append(f"{row.get('id')}: non-first-party Knowledge Bank full text")
        if not str(row.get("url", "")).startswith("https://www.superlinear.academy/"):
            errors.append(f"{row.get('id')}: unexpected Knowledge Bank source URL")

    for label, rows, id_prefix in (
        ("community post", community_post_rows, "circle-"),
        ("community comment", community_comment_rows, "circle-comment-"),
    ):
        ids = [row.get("id") for row in rows]
        if len(ids) != len(set(ids)):
            errors.append(f"duplicate IDs in {label} catalog")
        for row in rows:
            if not str(row.get("id", "")).startswith(id_prefix):
                errors.append(f"{row.get('id')}: unexpected {label} ID")
            if row.get("author") != "Yuzheng Sun" or row.get("rights_scope") != "first-party":
                errors.append(f"{row.get('id')}: non-first-party {label} content")
            if not row.get("full_text_included") or not row.get("corpus_path"):
                errors.append(f"{row.get('id')}: missing {label} full text")
            if not str(row.get("url", "")).startswith("https://www.superlinear.academy/"):
                errors.append(f"{row.get('id')}: unexpected {label} source URL")

    expected_community_post_files = {row.get("corpus_path") for row in community_post_rows}
    actual_community_post_files = {
        str(path.relative_to(ROOT)) for path in (ROOT / "corpus" / "community-posts").glob("*.md")
    }
    if expected_community_post_files != actual_community_post_files:
        errors.append("community post catalog/files mismatch")
    expected_community_comment_files = {row.get("corpus_path") for row in community_comment_rows}
    actual_community_comment_files = {
        str(path.relative_to(ROOT)) for path in (ROOT / "corpus" / "community-comments").glob("*.md")
    }
    if expected_community_comment_files != actual_community_comment_files:
        errors.append("community comment catalog/files mismatch")
    if comment_policy.get("comments_included") != len(community_comment_rows):
        errors.append("community comment policy/catalog count mismatch")
    if int(comment_policy.get("source_comments_reviewed") or 0) < len(community_comment_rows):
        errors.append("community comment policy reviewed count is invalid")

    community_post_ids = {row.get("id") for row in community_post_rows}
    for row in community_comment_rows:
        if row.get("parent_post_id") not in community_post_ids:
            errors.append(f"{row.get('id')}: comment parent is not an included Yuzheng post")
        if row.get("source_visibility") != "public":
            errors.append(f"{row.get('id')}: comment source is not public")
        if not row.get("parent_post_title"):
            errors.append(f"{row.get('id')}: comment is missing first-party parent title")
        corpus_path = ROOT / str(row.get("corpus_path") or "")
        if not corpus_path.is_file():
            continue
        text = corpus_path.read_text(encoding="utf-8")
        urls = URL_PATTERN.findall(text)
        source_url = str(row.get("url") or "")
        if len(urls) != 2 or any(url != source_url for url in urls):
            errors.append(f"{row.get('id')}: comment contains a non-canonical or extra URL")
        without_urls = URL_PATTERN.sub("", text)
        if BARE_DOMAIN_PATTERN.search(without_urls):
            errors.append(f"{row.get('id')}: comment contains a bare domain")
        body = text.split("\n\n", 2)[-1]
        if COMMENT_SENSITIVE_PATTERN.search(body):
            errors.append(f"{row.get('id')}: comment contains sensitive-context hint")
        if body.lstrip().startswith(("“", '"')):
            errors.append(f"{row.get('id')}: comment begins with a possible third-party quotation")
        if re.search(r"(?m)^\s*>", body):
            errors.append(f"{row.get('id')}: comment contains a possible third-party block quotation")
        if "@" in body:
            errors.append(f"{row.get('id')}: comment contains an unredacted mention")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for value, label in (
        (len(community_post_rows), "篇"),
        (len(community_comment_rows), "条"),
    ):
        if f"{value} {label}" not in readme:
            errors.append(f"README.md does not state current {value} {label} corpus count")

    for row in video_rows:
        if row.get("transcript_included") and row.get("rights_scope") != "first-party":
            errors.append(f"{row.get('id')}: mixed-speaker transcript included")
        if row.get("transcript_included") and (
            row.get("speaker_classification") != "solo-yuzheng"
            or row.get("review_status") != "approved"
        ):
            errors.append(f"{row.get('id')}: transcript lacks positive speaker-rights approval")
        if row.get("transcript_included") and row.get("guest_names"):
            errors.append(f"{row.get('id')}: known guest transcript included")
        if not str(row.get("url", "")).startswith("https://www.youtube.com/watch?v="):
            errors.append(f"{row.get('id')}: unexpected video source URL")

    included_video_ids = {
        row.get("video_id") for row in video_rows if row.get("transcript_included")
    }
    if included_video_ids != transcript_allowlist:
        missing = sorted(transcript_allowlist - included_video_ids)
        unexpected = sorted(included_video_ids - transcript_allowlist)
        errors.append(
            "video transcript catalog/allowlist mismatch"
            + (f"; missing={','.join(missing)}" if missing else "")
            + (f"; unexpected={','.join(unexpected)}" if unexpected else "")
        )
    conflicts = sorted(transcript_allowlist & set(rights_overrides))
    if conflicts:
        errors.append("video allowlist conflicts with manual exclusions: " + ", ".join(conflicts))

    for pattern in (ROOT / "context").glob("*.md"):
        text = pattern.read_text(encoding="utf-8")
        if "license: CC-BY-4.0" not in text:
            errors.append(f"{pattern.relative_to(ROOT)}: missing content license")
    for pattern in (ROOT / "examples").glob("*.md"):
        text = pattern.read_text(encoding="utf-8")
        if "author: Yuzheng Sun" not in text or "license: CC-BY-4.0" not in text:
            errors.append(f"{pattern.relative_to(ROOT)}: missing first-party attribution/license")
    for directory in (
        ROOT / "corpus" / "community-posts",
        ROOT / "corpus" / "community-comments",
        ROOT / "corpus" / "videos",
    ):
        for pattern in directory.glob("*.md") if directory.exists() else []:
            text = pattern.read_text(encoding="utf-8")
            if "author: \"Yuzheng Sun\"" not in text or "license: \"CC-BY-4.0\"" not in text:
                errors.append(f"{pattern.relative_to(ROOT)}: missing first-party attribution/license")
            if "third_party_exclusions: true" not in text:
                errors.append(f"{pattern.relative_to(ROOT)}: missing third-party rights notice")

    return {
        "community_posts_catalog": len(community_post_rows),
        "community_posts_full_text": sum(
            bool(row.get("full_text_included")) for row in community_post_rows
        ),
        "community_comments_included": len(community_comment_rows),
        "community_comments_reviewed": int(
            comment_policy.get("source_comments_reviewed") or 0
        ),
        "knowledge_bank_catalog": len(kb_rows),
        "knowledge_bank_full_text": sum(bool(row.get("full_text_included")) for row in kb_rows),
        "video_catalog": len(video_rows),
        "video_transcripts": sum(bool(row.get("transcript_included")) for row in video_rows),
        "video_metadata_only": sum(not bool(row.get("transcript_included")) for row in video_rows),
        "known_guest_videos": sum(bool(row.get("guest_names")) for row in video_rows),
    }


def build_manifest(stats: dict[str, int]) -> dict:
    return {
        "schema_version": 1,
        "snapshot_at": "2026-08-30",
        "repository": "sunyuzheng/lizheng-open-context",
        "intended_visibility": "public",
        "filters": {
            "community_posts_full_text": "current Circle-search posts authored by YZ｜立正 plus one first-party Knowledge Bank item preserved from the earlier public snapshot; archived and hidden test spaces excluded; contact data redacted",
            "community_comments_full_text": "first-party comments on included Yuzheng-authored posts, from discussion spaces with at least 80 effective characters; member mentions, contact data, sensitive/private context, third-party leading quotations, and all inline links removed",
            "knowledge_bank_full_text": "first-party Knowledge Bank posts point to the unified community-post corpus; other authors remain metadata-only",
            "videos": "youtube public + normal_video + ready_public_normal + local_status ok",
            "video_full_text": "explicit V1 solo-Yuzheng allowlist + timed transcript + no conflicting guest/mixed-speaker signal",
            "book": "author-owned complete framework reference and chapter map; no publisher-formatted assets",
        },
        "counts": stats,
        "files": [
            {
                "path": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in public_files()
        ],
    }


def validate_manifest(expected: dict, errors: list[str]) -> None:
    if not MANIFEST.is_file():
        errors.append("release-manifest.json is missing; run with --write-manifest")
        return
    actual = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if actual != expected:
        errors.append("release-manifest.json is stale; rerun with --write-manifest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-manifest", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    errors: list[str] = []
    validate_sensitive_data(errors)
    validate_internal_links(errors)
    try:
        stats = validate_rights(errors)
    except ValueError as exc:
        errors.append(str(exc))
        stats = {}
    expected = build_manifest(stats)
    if args.write_manifest and not errors:
        MANIFEST.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        validate_manifest(expected, errors)
    if errors:
        print("Release validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(json.dumps({"status": "ok", "counts": stats, "files": len(expected["files"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
