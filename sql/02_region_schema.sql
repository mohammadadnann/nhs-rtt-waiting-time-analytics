-- =====================================================================
-- NHS RTT Waiting Times — Region dimension
-- Adds Region as a real, queryable dimension, sitting one level above the
-- ICB information I already have via dim_providers.provider_parent_code.
-- Run this after 01_schema.sql, before loading the region lookup data.
-- =====================================================================

USE nhs_rtt_analytics;

-- ---------------------------------------------------------------------
-- Dimension: NHS England regions (7 regions cover all of England)
-- ---------------------------------------------------------------------
CREATE TABLE dim_regions (
    region_code   VARCHAR(10)  NOT NULL PRIMARY KEY,
    region_name   VARCHAR(100) NOT NULL
);

-- ---------------------------------------------------------------------
-- Lookup: which ICB sits in which region. I keep this separate from
-- dim_providers rather than adding a region column directly onto it,
-- since the source I load this from (ONS) codes ICBs independently of
-- how NHS England's own RTT files code providers, so this stays a clean
-- reference table that I join through rather than a column I would need
-- to keep in sync by hand.
-- ---------------------------------------------------------------------
CREATE TABLE dim_icb_region_map (
    icb_code      VARCHAR(10)  NOT NULL PRIMARY KEY,
    icb_name      VARCHAR(150) NOT NULL,
    region_code   VARCHAR(10)  NOT NULL,
    CONSTRAINT fk_icb_region FOREIGN KEY (region_code) REFERENCES dim_regions(region_code)
);