# Contributing

Contributions that improve retrieval, provenance, corrections, accessibility, and public-source coverage are welcome.

Before opening a pull request:

1. confirm the source was public at the canonical URL;
2. confirm the author or speaker and set the correct rights scope;
3. do not paste private, paid, member-only, deleted, leaked, or personally identifying material;
4. preserve publication dates and source links;
5. run `python3 scripts/validate_release.py`;
6. describe whether the change adds source material, changes interpretation, or only fixes tooling.

A new full video transcript also requires a deliberate entry in `config/video-transcript-allowlist.txt`. Absence from the guest index is not approval. If a title, guest record, or manual exclusion conflicts with the allowlist, the export must fail until a maintainer resolves the classification.

Do not open a public issue containing the sensitive material you want removed. Identify only the repository path and the reason at the minimum level needed for maintainers to act.
