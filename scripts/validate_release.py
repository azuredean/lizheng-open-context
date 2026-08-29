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
    video_catalog_path = ROOT / "catalog" / "videos.jsonl"
    if not kb_catalog_path.is_file():
        errors.append("catalog/knowledge-bank.jsonl is missing")
        kb_rows = []
    else:
        kb_rows = read_jsonl(kb_catalog_path)
    if not video_catalog_path.is_file():
        errors.append("catalog/videos.jsonl is missing")
        video_rows = []
    else:
        video_rows = read_jsonl(video_catalog_path)

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
    for directory in (ROOT / "corpus" / "knowledge-bank", ROOT / "corpus" / "videos"):
        for pattern in directory.glob("*.md") if directory.exists() else []:
            text = pattern.read_text(encoding="utf-8")
            if "author: \"Yuzheng Sun\"" not in text or "license: \"CC-BY-4.0\"" not in text:
                errors.append(f"{pattern.relative_to(ROOT)}: missing first-party attribution/license")
            if "third_party_exclusions: true" not in text:
                errors.append(f"{pattern.relative_to(ROOT)}: missing third-party rights notice")

    return {
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
        "snapshot_at": "2026-08-29",
        "repository": "sunyuzheng/kedaibiao-open-context",
        "intended_visibility": "public",
        "filters": {
            "knowledge_bank_full_text": "public Knowledge Bank posts authored by YZ｜立正",
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
