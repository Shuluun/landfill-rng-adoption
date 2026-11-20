# Source adjudications and reproduction references

These tables preserve the evidence used by the locked deployment ledger. Rebuilding the model reads the decisions in these files. Reviewing the underlying evidence is a separate activity.

| File | Origin and date | Fields and role |
|---|---|---|
| [full_verification_30.csv](full_verification_30.csv) | Archived November 9, 2026, stratified site audit | Sample rank, Landfill ID, GHGRP ID, registered year, stratum, external first-gas year and date, original source URL, verdict and notes. The verdict and timing are inherited evidence decisions. |
| [never_operational_full_36_final.csv](never_operational_full_36_final.csv) | Archived November 9, 2026, targeted planned or construction audit | Site ID, registered year, external start year, source, operational status class, electricity-to-RNG label and adjudication notes. The classifications are inherited evidence decisions. |
| [targeted_adjudications.csv](../rng_mainline_strengthening_v1/evidence/targeted_adjudications.csv) | Frozen November 10, 2026, targeted project review | Site and parent project keys, decision, date bounds, scenario year, source IDs, production-system identity and reason. |
| [targeted_sources.csv](../rng_mainline_strengthening_v1/evidence/targeted_sources.csv) | Source catalog accompanying the targeted project review | Source ID and landfill ID, source URL, date, locator and paraphrase. |
| [reproduction_reference](reproduction_reference/) | Frozen diagnostic and legacy figure references | Archived numerical fields retained for comparison and display. The archive stores the original trace and selected calculation fields without local command and workstation metadata. |

[provenance.json](provenance.json) gives each source path, original SHA-256, packaged SHA-256 and any selected JSON fields. The audit CSVs retain their original bytes. The locked [site-level risk ledger](../rng_mainline_strengthening_v1/results/mainline/run_007/site_risk_ledger.csv) and [event ledger](../rng_mainline_strengthening_v1/results/mainline/run_007/event_ledger.csv) record which cases entered the main sample and which evidence still awaits independent author review.
