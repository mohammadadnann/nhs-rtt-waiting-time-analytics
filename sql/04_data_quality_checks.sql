-- NHS RTT Waiting Times — data quality checks
-- I run these after loading data, not as part of the main analysis. Each
-- one checks something that could quietly break a query further down the
-- pipeline if it went unnoticed, rather than checking things that would
-- obviously error out on their own.

USE nhs_rtt_analytics;

-- Check 1: row count per month
-- Each month's raw file has around 180,000 wide rows, which unpivot into
-- roughly 1.0 to 1.4 million long fact rows depending on how many bands
-- had a nonzero count that month. A month that is wildly outside this
-- range would suggest a bad or partial file, not real NHS activity.
SELECT
    period_date,
    COUNT(*) AS fact_rows,
    COUNT(DISTINCT provider_code) AS distinct_providers,
    SUM(patient_count) AS total_patients
FROM fact_rtt_waiting_times
GROUP BY period_date
ORDER BY period_date;


-- Check 2: are all 6 expected months present, with no gap in between
-- I check this by counting distinct months and comparing the earliest and
-- latest against how many months should exist between them. A gap here
-- would mean a file was missed or failed to load silently.
SELECT
    COUNT(DISTINCT period_date) AS months_loaded,
    MIN(period_date) AS earliest_month,
    MAX(period_date) AS latest_month,
    PERIOD_DIFF(
        DATE_FORMAT(MAX(period_date), '%Y%m'),
        DATE_FORMAT(MIN(period_date), '%Y%m')
    ) + 1 AS months_expected_if_no_gap
FROM fact_rtt_waiting_times;


-- Check 3: any fact rows pointing to a provider, commissioner, treatment
-- function, or band that does not actually exist in the dimension tables
-- This should always return zero rows, since the foreign keys in the
-- schema are supposed to prevent this. I check it anyway as a second line
-- of defence, since a bulk load using to_sql can behave differently to a
-- normal insert if foreign key checks were ever disabled during a run.
SELECT 'orphaned provider_code' AS issue, COUNT(*) AS row_count
FROM fact_rtt_waiting_times f
LEFT JOIN dim_providers p ON f.provider_code = p.provider_code
WHERE p.provider_code IS NULL

UNION ALL

SELECT 'orphaned treatment_function_code', COUNT(*)
FROM fact_rtt_waiting_times f
LEFT JOIN dim_treatment_functions tf ON f.treatment_function_code = tf.treatment_function_code
WHERE tf.treatment_function_code IS NULL

UNION ALL

SELECT 'orphaned band_id', COUNT(*)
FROM fact_rtt_waiting_times f
LEFT JOIN dim_weeks_bands b ON f.band_id = b.band_id
WHERE b.band_id IS NULL;


-- Check 4: no duplicate fact rows
-- The schema has a unique key on period_date, provider_code,
-- commissioner_code, treatment_function_code, rtt_part_type, and band_id,
-- so MySQL itself should refuse a true duplicate. This confirms that
-- constraint is actually doing its job rather than assuming it is.
SELECT
    period_date, provider_code, commissioner_code,
    treatment_function_code, rtt_part_type, band_id,
    COUNT(*) AS duplicate_count
FROM fact_rtt_waiting_times
GROUP BY period_date, provider_code, commissioner_code,
         treatment_function_code, rtt_part_type, band_id
HAVING COUNT(*) > 1;


-- Check 5: providers that do not resolve to an NHS region
-- I already know this returns 2 providers, both using an ICB code from
-- before the April 2026 ICB mergers, which the current ONS region lookup
-- does not contain. I keep this query rather than silently filtering
-- these providers out, since a future reload with an updated region
-- lookup should bring this count down to zero, and this check is how I
-- would notice that.
SELECT
    p.provider_code, p.provider_name, p.provider_parent_code, p.provider_parent_name
FROM dim_providers p
LEFT JOIN dim_icb_region_map m ON p.provider_parent_code = m.icb_code
WHERE m.icb_code IS NULL AND p.provider_parent_code IS NOT NULL;


-- Check 6: national breach rate sanity check across months
-- I know from NHS England's own published figures that the national RTT
-- breach rate has been sitting in the mid to high 30s percent through
-- late 2025 and early 2026. A month showing something wildly outside
-- that range, for example under 10% or over 60%, would suggest a loading
-- or unpivoting problem rather than a real shift in NHS performance.
SELECT
    period_date,
    ROUND(SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) * 100.0
          / SUM(f.patient_count), 2) AS breach_rate_pct
FROM fact_rtt_waiting_times f
JOIN dim_weeks_bands b ON f.band_id = b.band_id
GROUP BY period_date
ORDER BY period_date;
