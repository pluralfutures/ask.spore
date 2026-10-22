# Accepted eval baselines

Newest last. Written by `python -m eval accept-baseline`; the gate (`python -m eval gate`,
CI) compares every newer committed run against the last one.

| Date | Run | Previous | Verdict | Reason |
| --- | --- | --- | --- | --- |
| 2026-10-22 | `20261018T234701Z-a981e7bd8911` | `-` | first baseline | Recorded by hand when the gate was built (P1b-15 b): the Phase 0 real-corpus baseline that the Phase 1a gate runs were compared with (findings 1a G7 to G9); already redacted (findings 1a §12). The Phase 1a gate runs were not committed. `20261018T235229Z-11fba9927728` (the P0-20 threshold 0.25 run, findings 1a section 5) was reviewed then and is history (`reviewed-through`). |
