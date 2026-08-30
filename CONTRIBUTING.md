# Contributing

Contributions that improve retrieval, provenance, corrections, accessibility, and public-source coverage are welcome.

Before opening a pull request:

1. confirm the canonical URL and original access state;
2. confirm the author or speaker and set the correct rights scope;
3. do not paste private messages, another member's content, leaked material, credentials, or personally identifying data; author-owned Superlinear posts from member spaces are accepted only through the maintainer's reviewed export;
4. preserve publication dates and source links;
5. run `python3 scripts/validate_release.py`;
6. describe whether the change adds source material, changes interpretation, or only fixes tooling.

A new full video transcript also requires a deliberate entry in `config/video-transcript-allowlist.txt`. Absence from the guest index is not approval. If a title, guest record, or manual exclusion conflicts with the allowlist, the export must fail until a maintainer resolves the classification.

New community comments must pass `config/community-comment-policy.json`. Do not work around the filter by manually copying a member name, surrounding conversation, contact detail, or private-context fragment into the corpus.

Do not open a public issue containing the sensitive material you want removed. Identify only the repository path and the reason at the minimum level needed for maintainers to act.
