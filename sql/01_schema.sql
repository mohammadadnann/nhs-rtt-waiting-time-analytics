-- =====================================================================
-- NHS England RTT Waiting Times — Database Schema
-- Project: NHS RTT SQL-Driven Business Analytics & Breach Risk Forecasting
-- Author: Mohammad Adnan Iqbal
-- =====================================================================

CREATE DATABASE IF NOT EXISTS nhs_rtt_analytics
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE nhs_rtt_analytics;

-- ---------------------------------------------------------------------
-- Dimension: NHS Provider Trusts (with parent org for regional rollups)
-- ---------------------------------------------------------------------
CREATE TABLE dim_providers (
    provider_code           VARCHAR(10)  NOT NULL PRIMARY KEY,
    provider_name           VARCHAR(150) NOT NULL,
    provider_parent_code    VARCHAR(10)  NULL,
    provider_parent_name    VARCHAR(150) NULL,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------
-- Dimension: Commissioners (ICBs), with parent org
-- ---------------------------------------------------------------------
CREATE TABLE dim_commissioners (
    commissioner_code        VARCHAR(10)  NOT NULL PRIMARY KEY,
    commissioner_name        VARCHAR(150) NOT NULL,
    commissioner_parent_code VARCHAR(10)  NULL,
    commissioner_parent_name VARCHAR(150) NULL,
    created_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------
-- Dimension: Treatment Functions (specialties)
-- ---------------------------------------------------------------------
CREATE TABLE dim_treatment_functions (
    treatment_function_code VARCHAR(10)  NOT NULL PRIMARY KEY,
    treatment_function_name VARCHAR(150) NOT NULL,
    created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------
-- Dimension: Waiting time week-bands (unpivoted from wide CSV columns)
-- Covers Gt 00-01 weeks up to Gt 104+ weeks, matching the real NHS file
-- ---------------------------------------------------------------------
CREATE TABLE dim_weeks_bands (
    band_id       INT AUTO_INCREMENT PRIMARY KEY,
    band_label    VARCHAR(30)  NOT NULL UNIQUE,
    band_lower    SMALLINT     NOT NULL,
    band_upper    SMALLINT     NULL,
    breach_flag   BOOLEAN      NOT NULL DEFAULT FALSE
);

-- ---------------------------------------------------------------------
-- Fact table: one row per provider + specialty + period + part-type + band
-- ---------------------------------------------------------------------
CREATE TABLE fact_rtt_waiting_times (
    fact_id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    period_date              DATE        NOT NULL,
    provider_code            VARCHAR(10) NOT NULL,
    commissioner_code        VARCHAR(10) NULL,
    treatment_function_code  VARCHAR(10) NOT NULL,
    rtt_part_type            VARCHAR(30) NOT NULL,
    band_id                  INT         NOT NULL,
    patient_count            INT         NOT NULL DEFAULT 0,
    created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_fact_provider FOREIGN KEY (provider_code) REFERENCES dim_providers(provider_code),
    CONSTRAINT fk_fact_commissioner FOREIGN KEY (commissioner_code) REFERENCES dim_commissioners(commissioner_code),
    CONSTRAINT fk_fact_treatment_function FOREIGN KEY (treatment_function_code) REFERENCES dim_treatment_functions(treatment_function_code),
    CONSTRAINT fk_fact_band FOREIGN KEY (band_id) REFERENCES dim_weeks_bands(band_id),

    UNIQUE KEY uq_fact_row (period_date, provider_code, treatment_function_code, rtt_part_type, band_id)
);

-- ---------------------------------------------------------------------
-- Indexes to support analytical queries (window functions, trend analysis)
-- ---------------------------------------------------------------------
CREATE INDEX idx_fact_period ON fact_rtt_waiting_times (period_date);
CREATE INDEX idx_fact_provider_period ON fact_rtt_waiting_times (provider_code, period_date);
CREATE INDEX idx_fact_treatment_period ON fact_rtt_waiting_times (treatment_function_code, period_date);