-- NHS England RTT Waiting Times analysis queries
-- Database currently holds 6 months of data, November 2025 through April 2026.
-- Queries 2, 3, 4, and 7 rank providers or specialties as a leaderboard, so I
-- filter them to the latest loaded month using MAX(period_date) rather than
-- hardcoding a date. Without this filter, these queries would sum the same
-- waiting patients across every month they appear in the incomplete pathway
-- snapshot, since a patient still waiting in April was already counted in
-- November, December, January, February, and March too. That is not a real
-- total, it is the same person counted up to six times.
-- Queries 5 and 6 are the trend queries, and correctly use every month on
-- purpose, since a trend needs the full history to compare across.

USE nhs_rtt_analytics;

-- Query 1: national breach rate against the 18 week RTT standard, latest month
-- I filter to the latest period_date here too, for the same reason as
-- queries 2, 3, 4, and 7. A breach rate summed across 6 overlapping monthly
-- snapshots would not be a meaningful percentage.
SELECT
    SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) AS breaching_patients,
    SUM(f.patient_count) AS total_patients,
    ROUND(
        SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) * 100.0
        / SUM(f.patient_count), 2
    ) AS breach_rate_pct
FROM fact_rtt_waiting_times f
JOIN dim_weeks_bands b ON f.band_id = b.band_id
WHERE f.period_date = (SELECT MAX(period_date) FROM fact_rtt_waiting_times);


-- Query 2: providers ranked by breach rate, worst first, latest month
-- The CTE aggregates patient counts per provider for the latest month only,
-- then RANK orders them by breach rate.
--   1. Highest breach rate percentage gets rank 1
--   2. Next highest breach rate percentage gets rank 2
--   3. And so on, down to the lowest breach rate percentage
-- I filter out providers under 100 patients so a handful of cases does not produce a misleading percentage.
WITH provider_breach_summary AS (
    SELECT
        p.provider_code,
        p.provider_name,
        SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) AS breaching_patients,
        SUM(f.patient_count) AS total_patients
    FROM fact_rtt_waiting_times f
    JOIN dim_providers p ON f.provider_code = p.provider_code
    JOIN dim_weeks_bands b ON f.band_id = b.band_id
    WHERE f.period_date = (SELECT MAX(period_date) FROM fact_rtt_waiting_times)
    GROUP BY p.provider_code, p.provider_name
    HAVING SUM(f.patient_count) >= 100
)
SELECT
    provider_code,
    provider_name,
    total_patients,
    breaching_patients,
    ROUND(breaching_patients * 100.0 / total_patients, 2) AS breach_rate_pct,
    RANK() OVER (ORDER BY breaching_patients * 1.0 / total_patients DESC) AS breach_rank
FROM provider_breach_summary
ORDER BY breach_rank
LIMIT 20;


-- Query 3: breach rate by treatment function (specialty), ranked nationally, latest month
-- Same pattern as Query 2, grouped by specialty instead of provider.
WITH specialty_breach_summary AS (
    SELECT
        tf.treatment_function_code,
        tf.treatment_function_name,
        SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) AS breaching_patients,
        SUM(f.patient_count) AS total_patients
    FROM fact_rtt_waiting_times f
    JOIN dim_treatment_functions tf ON f.treatment_function_code = tf.treatment_function_code
    JOIN dim_weeks_bands b ON f.band_id = b.band_id
    WHERE f.period_date = (SELECT MAX(period_date) FROM fact_rtt_waiting_times)
    GROUP BY tf.treatment_function_code, tf.treatment_function_name
)
SELECT
    treatment_function_name,
    total_patients,
    breaching_patients,
    ROUND(breaching_patients * 100.0 / total_patients, 2) AS breach_rate_pct,
    RANK() OVER (ORDER BY breaching_patients * 1.0 / total_patients DESC) AS breach_rank
FROM specialty_breach_summary
ORDER BY breach_rank;


-- Query 4: breach rate aggregated to ICB level, latest month
-- provider_parent_name holds the Integrated Care Board each provider reports into,
-- so grouping on it gives a regional rollup without needing a separate join.
SELECT
    p.provider_parent_name AS integrated_care_board,
    SUM(f.patient_count) AS total_patients,
    SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) AS breaching_patients,
    ROUND(
        SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) * 100.0
        / SUM(f.patient_count), 2
    ) AS breach_rate_pct
FROM fact_rtt_waiting_times f
JOIN dim_providers p ON f.provider_code = p.provider_code
JOIN dim_weeks_bands b ON f.band_id = b.band_id
WHERE p.provider_parent_name IS NOT NULL
    AND f.period_date = (SELECT MAX(period_date) FROM fact_rtt_waiting_times)
GROUP BY p.provider_parent_name
ORDER BY breach_rate_pct DESC;


-- Query 5 (TREND): month on month change in breach rate per provider
-- I calculate breach_rate_pct once in the first CTE, then use LAG in a
-- second CTE to pull in each provider's previous month value. I need this
-- as two separate steps because SQL will not let me filter on a column
-- calculated by a window function in the same SELECT that creates it, so
-- the WHERE clause at the end runs against the already finished result.
-- This query correctly uses every month, unlike queries 1 to 4 and 7,
-- since a month on month trend needs the full history to compare across.
WITH monthly_provider_breach AS (
    SELECT
        p.provider_code,
        p.provider_name,
        f.period_date,
        ROUND(SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END)
              * 100.0 / SUM(f.patient_count), 2) AS breach_rate_pct
    FROM fact_rtt_waiting_times f
    JOIN dim_providers p ON f.provider_code = p.provider_code
    JOIN dim_weeks_bands b ON f.band_id = b.band_id
    GROUP BY p.provider_code, p.provider_name, f.period_date
),
provider_trend AS (
    SELECT
        *,
        LAG(breach_rate_pct) OVER (PARTITION BY provider_code ORDER BY period_date) AS prior_month_breach_rate_pct,
        breach_rate_pct - LAG(breach_rate_pct) OVER (PARTITION BY provider_code ORDER BY period_date) AS change_in_breach_rate_pct
    FROM monthly_provider_breach
)
SELECT *
FROM provider_trend
WHERE prior_month_breach_rate_pct IS NOT NULL
ORDER BY provider_code, period_date;


-- Query 6 (TREND): three month rolling average of the national breach rate
-- The window frame ROWS BETWEEN 2 PRECEDING AND CURRENT ROW averages the
-- current month with the two before it. This query also correctly uses
-- every month on purpose, same reason as Query 5.
WITH monthly_national_breach AS (
    SELECT
        f.period_date,
        SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) * 100.0
            / SUM(f.patient_count) AS breach_rate_pct
    FROM fact_rtt_waiting_times f
    JOIN dim_weeks_bands b ON f.band_id = b.band_id
    GROUP BY f.period_date
)
SELECT
    period_date,
    ROUND(breach_rate_pct, 2) AS breach_rate_pct,
    ROUND(AVG(breach_rate_pct) OVER (
        ORDER BY period_date
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ), 2) AS rolling_3month_avg_breach_rate_pct
FROM monthly_national_breach
ORDER BY period_date;


-- Query 7: providers with the highest share of patients waiting 52+ weeks, latest month
-- 52 week waits are reported by NHS England as their own metric separate from
-- the 18 week standard, so I track it here as a distinct measure of severity.
WITH long_wait_summary AS (
    SELECT
        p.provider_code,
        p.provider_name,
        SUM(CASE WHEN b.band_lower >= 52 THEN f.patient_count ELSE 0 END) AS patients_52plus_weeks,
        SUM(f.patient_count) AS total_patients
    FROM fact_rtt_waiting_times f
    JOIN dim_providers p ON f.provider_code = p.provider_code
    JOIN dim_weeks_bands b ON f.band_id = b.band_id
    WHERE f.period_date = (SELECT MAX(period_date) FROM fact_rtt_waiting_times)
    GROUP BY p.provider_code, p.provider_name
    HAVING SUM(f.patient_count) >= 100
)
SELECT
    provider_code,
    provider_name,
    total_patients,
    patients_52plus_weeks,
    ROUND(patients_52plus_weeks * 100.0 / total_patients, 2) AS pct_waiting_52plus_weeks,
    RANK() OVER (ORDER BY patients_52plus_weeks * 1.0 / total_patients DESC) AS long_wait_rank
FROM long_wait_summary
ORDER BY long_wait_rank
LIMIT 20;


-- Query 8: breach rate by NHS region, latest month
-- I join fact_rtt_waiting_times to dim_providers to get each provider's ICB
-- code, then to dim_icb_region_map to get the region that ICB sits in. A
-- small number of providers use an ICB code from before the April 2026 ICB
-- mergers, which will not find a match in the current region lookup, so
-- their rows fall out of this query. That is expected, not a bug, and I
-- have noted it in my data quality notes rather than patching around it.

USE nhs_rtt_analytics;
SELECT
    r.region_name,
    SUM(f.patient_count) AS total_patients,
    SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) AS breaching_patients,
    ROUND(
        SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) * 100.0
        / SUM(f.patient_count), 2
    ) AS breach_rate_pct
FROM fact_rtt_waiting_times f
JOIN dim_providers p ON f.provider_code = p.provider_code
JOIN dim_icb_region_map m ON p.provider_parent_code = m.icb_code
JOIN dim_regions r ON m.region_code = r.region_code
JOIN dim_weeks_bands b ON f.band_id = b.band_id
WHERE f.period_date = (SELECT MAX(period_date) FROM fact_rtt_waiting_times)
GROUP BY r.region_name
ORDER BY breach_rate_pct DESC;