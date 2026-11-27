# Agensi.io marketplace release checklist

- Ensure SKILL.md is at the ZIP root, not nested under another directory.
- Frontmatter defines non-empty name and description fields.
- Include readable text files and small, self-contained scripts only.
- Keep every helper script below 20 KB.
- Exclude .git, caches, virtual environments, datasets, PDFs, DOCX examples, credentials, and binaries.
- Keep the archive below 50 MB and 1,000 files.
- Test the skill locally with a small PDF before publishing.
- Review trigger description, prerequisites, CLI flags, output files, troubleshooting, and known limitations.
- Run the bundled verifier on a successful output directory.
- Confirm the skill does not request credentials in chat or transmit user documents without consent.
- Review marketplace listing details, category, pricing, screenshots, and support information before submission.

StructuraRAG's package is an integration helper. Users still need Python 3.12 and a StructuraRAG repository checkout; the skill does not bundle the full converter source or third-party runtime.
