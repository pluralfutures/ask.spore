#!/usr/bin/env sh
# Ingest the synthetic corpus with the metadata packages/eval/sets/synthetic-v0.jsonl
# expects: its expected_source_ids are the canonical URLs below (example.org is a
# reserved domain; every organisation and figure in these files is invented).
#
# Run from the repository root with the API environment loaded (.env), after
# `ask-spore datasets sync`:
#
#   sh packages/eval/fixtures/corpus/ingest.sh
set -eu

DIR=packages/eval/fixtures/corpus
ASK="uv run --directory apps/api ask-spore"
BASE=https://example.org/synthetic

$ASK ingest "$PWD/$DIR/tidewater-offshore-wind-2026.pdf" --tag sample-reports \
  --title "Tidewater Offshore Wind Outlook 2026" \
  --publisher "Fictional Institute for Coastal Energy" \
  --published-on 2026-03-02 --licence "synthetic test fixture" \
  --canonical-url "$BASE/tidewater-offshore-wind-2026"

$ASK ingest "$PWD/$DIR/brightwater-heat-pumps-note.docx" --tag sample-analysis \
  --title "Analysis note: heat pump adoption in Brightwater" \
  --publisher "Synthetic Analysis Team" \
  --published-on 2026-05-14 --licence "own work" \
  --canonical-url "$BASE/brightwater-heat-pumps-note"

$ASK ingest "$PWD/$DIR/kestrel-valley-storage-briefing.pptx" --tag sample-analysis \
  --title "Battery storage in Kestrel Valley" \
  --publisher "Synthetic Analysis Team" \
  --published-on 2026-06-30 --licence "own work" \
  --canonical-url "$BASE/kestrel-valley-storage-briefing"

$ASK ingest "$PWD/$DIR/ferrow-hydrogen-pilot.html" --tag sample-web \
  --title "Ferrow hydrogen pilot results" \
  --publisher "Example Pages" \
  --published-on 2026-02-10 --licence "synthetic test fixture" \
  --canonical-url "$BASE/ferrow-hydrogen-pilot"

$ASK ingest "$PWD/$DIR/hollin-grid-tariffs.md" --tag sample-web \
  --title "Grid tariff reform in Hollin" \
  --publisher "Hollin Energy Regulator" \
  --published-on 2026-04-20 --licence "synthetic test fixture" \
  --canonical-url "$BASE/hollin-grid-tariffs"
