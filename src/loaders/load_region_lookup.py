"""
NHS Region dimension, data loading script

This script reads the ONS ICB to NHS England Region lookup and loads it as
two small dimension tables: dim_regions and dim_icb_region_map. Unlike the
monthly RTT files, this reference file barely changes, so I just clear and
reload both tables each run rather than building incremental logic for it.

The source file has one row per Sub ICB Location, so the same ICB and
region appear many times over. I deduplicate down to one row per ICB
before loading, since that is the grain I actually need for the join.
"""

import pandas as pd
from sqlalchemy import create_engine, text

DB_USER = "root"
DB_PASSWORD = "optima123!"
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_NAME = "nhs_rtt_analytics"

CSV_PATH = "data/reference/icb_region_lookup.csv"

engine = create_engine(
    f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

print("Reading ICB to Region lookup...")
df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
print(f"  {len(df):,} rows, {len(df.columns)} columns")

regions = (
    df[["NHSER26CDH", "NHSER26NM"]]
    .drop_duplicates()
    .rename(columns={"NHSER26CDH": "region_code", "NHSER26NM": "region_name"})
)
print(f"  {len(regions)} unique regions found")

icb_region_map = (
    df[["ICB26CDH", "ICB26NM", "NHSER26CDH"]]
    .drop_duplicates(subset=["ICB26CDH"])
    .rename(columns={
        "ICB26CDH": "icb_code",
        "ICB26NM": "icb_name",
        "NHSER26CDH": "region_code",
    })
)
print(f"  {len(icb_region_map)} unique ICBs found")

print("Clearing existing region tables so this script is safe to run again...")
with engine.begin() as conn:
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    conn.execute(text("TRUNCATE TABLE dim_icb_region_map"))
    conn.execute(text("TRUNCATE TABLE dim_regions"))
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

regions.to_sql("dim_regions", engine, if_exists="append", index=False, method="multi")
icb_region_map.to_sql("dim_icb_region_map", engine, if_exists="append", index=False, method="multi")
print("Loaded dim_regions and dim_icb_region_map")

print("\nChecking how many providers actually match an ICB in this lookup...")
with engine.connect() as conn:
    match_check = conn.execute(text("""
        SELECT
            COUNT(DISTINCT p.provider_code) AS total_providers,
            COUNT(DISTINCT CASE WHEN m.icb_code IS NOT NULL THEN p.provider_code END) AS matched_providers
        FROM dim_providers p
        LEFT JOIN dim_icb_region_map m ON p.provider_parent_code = m.icb_code
    """)).fetchone()
    print(f"  {match_check[1]:,} of {match_check[0]:,} providers matched to a region")

    unmatched = conn.execute(text("""
        SELECT DISTINCT p.provider_parent_code, p.provider_parent_name
        FROM dim_providers p
        LEFT JOIN dim_icb_region_map m ON p.provider_parent_code = m.icb_code
        WHERE m.icb_code IS NULL AND p.provider_parent_code IS NOT NULL
        LIMIT 10
    """)).fetchall()
    if unmatched:
        print("  A sample of provider_parent_codes that did not match, worth checking by hand:")
        for row in unmatched:
            print(f"    {row[0]}  {row[1]}")