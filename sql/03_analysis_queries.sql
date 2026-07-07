-- NHS England RTT Waiting Times analysis queries
-- Database currently holds one month of data (April 2026).
-- Queries 5 and 6 are marked TREND because they use LAG and rolling averages,
-- which only produce meaningful output once multiple months are loaded.

USE nhs_rtt_analytics;

-- Query 1: national breach rate against the 18 week RTT standard
-- I sum patient counts where breach_flag is true and divide by total patients.
SELECT
    SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) AS breaching_patients,
    SUM(f.patient_count) AS total_patients,
    ROUND(
        SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) * 100.0
        / SUM(f.patient_count), 2
    ) AS breach_rate_pct
FROM fact_rtt_waiting_times f
JOIN dim_weeks_bands b ON f.band_id = b.band_id;


-- Query 2: providers ranked by breach rate, worst first
-- The CTE aggregates patient counts per provider, then RANK orders them by breach rate.
--   1. Highest breach rate percentage gets rank 1
--   2. Next highest breach rate percentage gets rank 2
--   3. And so on, down to the lowest breach rate percentage
-- I filter out providers under 100 patients so a handful of cases does not produce a misleading percentage.
USE nhs_rtt_analytics;
WITH provider_breach_summary AS (
    SELECT
        p.provider_code,
        p.provider_name,
        SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) AS breaching_patients,
        SUM(f.patient_count) AS total_patients
    FROM fact_rtt_waiting_times f
    JOIN dim_providers p ON f.provider_code = p.provider_code
    JOIN dim_weeks_bands b ON f.band_id = b.band_id
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


-- Query 3: breach rate by treatment function (specialty), ranked nationally
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


-- Query 4: breach rate aggregated to ICB level
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
GROUP BY p.provider_parent_name
ORDER BY breach_rate_pct DESC;


-- Query 5 (TREND): month on month change in breach rate per provider
-- LAG pulls the previous period_date's breach rate into the same row as the current one,
-- so the difference can be calculated directly. With only April 2026 loaded,
-- prior_month_breach_rate_pct returns NULL for every row since there is no prior month yet.
WITH monthly_provider_breach AS (
    SELECT
        p.provider_code,
        p.provider_name,
        f.period_date,
        SUM(CASE WHEN b.breach_flag = TRUE THEN f.patient_count ELSE 0 END) AS breaching_patients,
        SUM(f.patient_count) AS total_patients
    FROM fact_rtt_waiting_times f
    JOIN dim_providers p ON f.provider_code = p.provider_code
    JOIN dim_weeks_bands b ON f.band_id = b.band_id
    GROUP BY p.provider_code, p.provider_name, f.period_date
)
SELECT
    provider_code,
    provider_name,
    period_date,
    ROUND(breaching_patients * 100.0 / total_patients, 2) AS breach_rate_pct,
    LAG(ROUND(breaching_patients * 100.0 / total_patients, 2)) OVER (
        PARTITION BY provider_code ORDER BY period_date
    ) AS prior_month_breach_rate_pct,
    ROUND(breaching_patients * 100.0 / total_patients, 2)
        - LAG(ROUND(breaching_patients * 100.0 / total_patients, 2)) OVER (
            PARTITION BY provider_code ORDER BY period_date
          ) AS change_in_breach_rate_pct
FROM monthly_provider_breach
ORDER BY provider_code, period_date;


-- Query 6 (TREND): three month rolling average of the national breach rate
-- The window frame ROWS BETWEEN 2 PRECEDING AND CURRENT ROW averages the
-- current month with the two before it. Needs three or more months loaded
-- before the average reflects an actual trend rather than a single value.
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


-- Query 7: providers with the highest share of patients waiting 52+ weeks
-- 52 week waits are reported by NHS England as their own metric separate from
-- the 18 week standard, so I tracked it here as a distinct measure of severity.
WITH long_wait_summary AS (
    SELECT
        p.provider_code,
        p.provider_name,
        SUM(CASE WHEN b.band_lower >= 52 THEN f.patient_count ELSE 0 END) AS patients_52plus_weeks,
        SUM(f.patient_count) AS total_patients
    FROM fact_rtt_waiting_times f
    JOIN dim_providers p ON f.provider_code = p.provider_code
    JOIN dim_weeks_bands b ON f.band_id = b.band_id
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