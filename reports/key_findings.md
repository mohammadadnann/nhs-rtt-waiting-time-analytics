# Key Findings

Data covers April 2026, one month, all NHS providers in England. Total patients on
incomplete RTT pathways after removing the C_999 total rollup rows: 9,764,370.

## National breach rate

36.79% of patients are waiting longer than the 18 week RTT standard.
That is 3,592,204 patients out of 9,764,370.

## Worst performing specialties

Every specialty in the top 9 is surgical, not medical. Ranked by breach rate:

1. Oral Surgery, 48.16%
2. Trauma and Orthopaedics, 45.78%, largest specialty by volume at 1,245,445 patients
3. Plastic Surgery, 45.23%
4. Ear Nose and Throat, 44.11%
5. Gynaecology, 42.01%

Trauma and Orthopaedics carries by far the largest patient volume of any specialty,
so even though four specialties have a higher percentage, T&O likely represents the
biggest absolute burden on the system. This lines up with how T&O is usually reported
as one of the most backlogged specialties nationally in real NHS statistics, which is
a good sign the data and the pipeline behind it are producing realistic numbers.

## Worst performing providers by breach rate

Ranks 9 to 20 are almost entirely private providers working under NHS contracts,
mostly Spire and Nuffield Health hospitals, with breach rates between 52% and 58%.
This likely reflects that these providers take on patients who already had long
waits before being referred to them for overflow capacity, rather than these
providers performing worse than NHS trusts on their own patients.

## Worst 52+ week waiters

This tracks a different NHS metric, the share of patients waiting over a year,
which NHS England reports separately from the 18 week standard.

1. Nuffield Health Brighton, 14.36%
2. The Robert Jones and Agnes Hunt Orthopaedic Hospital, 13.14%, 4,658 patients
3. Nuffield Health Brentwood, 12.47%
4. Oxleas NHS Foundation Trust, 11.59%
5. Spamedica Southampton, 10.48%

The Robert Jones and Agnes Hunt Hospital is a specialist NHS orthopaedic trust that
takes complex referrals from a wide area, and it consistently reports some of the
longest waits nationally in real NHS data, so seeing it rank 2 here is a good sign
the pipeline is producing trustworthy results.

Mid and South Essex NHS ranks 8 by percentage at 8.81%, but has 19,516 patients
waiting 52+ weeks, the largest absolute number of any provider in the list. Percentage
rank and absolute number of long waiters are two different things worth reporting
separately, since a smaller provider can have a higher percentage while a large
trust carries a bigger real world burden.

## Limitations

The database currently holds one month of data, April 2026. Two queries in
03_analysis_queries.sql are built for trend analysis using LAG and a rolling
average, and both run correctly, but return a single value or NULL since there
is no earlier month to compare against yet. Loading more monthly NHS RTT extracts
would let these queries show real month on month movement.

## Data cleaning note

The raw data included a row coded C_999 and labeled Total for every provider,
commissioner, and part type group, which duplicated the sum of the real specialty
rows in that group. Keeping it would have counted every patient twice and let
Total appear as its own row in specialty rankings. This was found and removed in
load_rtt_data.py before loading, which cut the total patient count from
19,528,740 down to the correct 9,764,370.