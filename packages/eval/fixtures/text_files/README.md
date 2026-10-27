# Text-file parse fixtures (P2B-06)

Synthetic files for the RAGFlow parser and chunking check of Markdown and plain-text
uploads (`design/specs/phase-2b-findings.md`, section 1). Every name, place and figure
is fictional. They are not part of the eval corpus and are not ingested by `ingest.sh`.

- `marrow-fen-water-survey.md`: three heading levels, a GFM table, lists, and
  non-ASCII text (accented Latin, Greek, Cyrillic, CJK, symbols and an emoji). No BOM,
  LF line endings. Long enough to make several chunks.
- `quillan-ferry-timetable-note.txt`: plain paragraphs, a column-aligned table in
  spaces, the same non-ASCII set, a UTF-8 byte-order mark and CRLF line endings.
