# Data Quality Notes

This documents the checks I ran on the NHS RTT dataset after loading 6
months of data (November 2025 to April 2026), and the issues I found and
either fixed or knowingly left as documented limitations. I am treating
this as a normal part of the pipeline, not a one off cleanup step, since
NHS RTT data has genuine quirks that would silently produce wrong numbers
if I trusted the raw files without checking them.

## Issues found and fixed during the project

### 1. C_999 total rollup rows (fixed in the ETL)

Each provider, commissioner, and part type group in the raw file includes
an extra row coded `C_999` and labelled "Total", which is just the sum of
the real specialty rows in that group. Loading it alongside the real rows
would double count every patient once under their real specialty and
again under this synthetic total. `load_rtt_data.py` filters these rows
out before anything else happens. This cut the April 2026 total patient
count from 19,528,740 down to the correct 9,764,370, roughly half, which
shows how serious this would have been if I left it unfixed.

### 2. Overlapping monthly snapshots inflating leaderboard queries (fixed in the SQL)

RTT "incomplete pathway" data is a snapshot of who is still waiting at the
end of each month, not a stream of new patients. A patient still waiting
in April was already counted in November, December, January, February,
and March too, since they are the same person still on the same list.
Once I loaded more than one month, my provider and specialty ranking
queries (originally queries 1, 2, 3, 4, and 7) were summing patient counts
across all loaded months as if they were separate people, inflating
totals by up to 6x for a provider present in every month. I fixed this by
filtering those queries to `MAX(period_date)`, so they always rank the
latest loaded month rather than a meaningless blend across months. The
trend queries (5 and 6) are unaffected, since they are supposed to use
every month on purpose.

### 3. Two providers not matching an NHS region (documented, not patched)

After adding the region dimension, 536 of 538 providers matched to a
region through their ICB code. The 2 that did not, NHS Suffolk and North
East Essex ICB (QJG) and NHS Surrey Heartlands ICB (QXU), are both real,
valid ICBs, not data errors. The explanation is a timing mismatch between
two official sources: the region lookup I used reflects the ICB structure
from the April 2026 ICB mergers, while these 2 providers' RTT records
still carry a pre merger ICB code. I chose to leave this as a documented
gap rather than manually remapping 2 providers by hand, since the correct
long term fix is loading an updated ONS lookup once one exists, and
`sql/04_data_quality_checks.sql` Check 5 is there specifically to tell me
when that count changes.

## Ongoing checks

`sql/04_data_quality_checks.sql` holds 6 checks I can rerun after every
load:

1. Row count per month, to catch a partial or corrupted file
2. Month coverage, to catch a silently skipped month
3. Orphaned foreign keys, to catch a bulk load problem
4. Duplicate fact rows, to confirm the unique constraint is doing its job
5. Providers not matching a region, expected to read 2 for now
6. National breach rate per month, sanity checked against NHS England's
   published figures for late 2025 and early 2026

## Known limitations, not yet addressed

- No patient level demographics (age, ethnicity, deprivation) in the
  current dataset. The Waiting List Minimum Dataset (WLMDS), published by
  NHS England alongside the monthly RTT release, would add this.
- 6 months of history is enough for a real trend and a defensible short
  term forecast, but not a full seasonal cycle. A 12 to 18 month range
  would strengthen any forecasting work built on top of this later.
