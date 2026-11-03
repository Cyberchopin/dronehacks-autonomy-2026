# Portable evidence package

The evidence here consists of byte-identical copies or explicitly sanitized derivatives of local audit captures. See [derivative-manifest.json](derivative-manifest.json) for each original and derivative SHA-256 and transformation. The original captures remain local and are not represented as included raw originals when sanitized. `<AUDIT_CHECKOUT>` replaces the private checkout root. The original command metadata's stdout/stderr hashes refer to the original raw streams; use the derivative manifest to check sanitized streams.

The captured `head` is the audited runtime revision, not this evidence commit. Historical command paths and timestamps are evidence of the earlier run; do not run a capture helper into the preserved output directory because it can overwrite files. Reproduce in a new checkout and output directory, using the documented environment and commands, and compare inputs, source hashes, results and limitations. Synthetic replay is not official simulation or flight evidence. The two original supplied inputs are not distributed; see [INPUTS.md](INPUTS.md).

The 11 command triplets preserve the four bounded test groups, Ruff checks, course replay, expanded safety probe, static inventory and its original failure, and remote DNS failure. Zero-byte stderr files are intentional. The local originals of other audit-process captures and the obsolete checksum index are not part of this package.

[SHA256SUMS](SHA256SUMS) hashes the selected audit documents, helpers, and portable files as staged Git blob bytes, using repository-root-relative paths. It excludes itself. The old local audit-root checksum index is not used and is not included.
