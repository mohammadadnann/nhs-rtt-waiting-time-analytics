"""
NHS England RTT Waiting Times — Data Loading Script
Project: NHS RTT SQL-Driven Business Analytics & Breach Risk Forecasting
Author: Mohammad Adnan Iqbal

What this script does:
1. Reads the raw NHS RTT "full extract" CSV (wide format — one column
   per waiting-time week-band).
2. Builds the 4 dimension tables (providers, commissioners, treatment
   functions, weeks-bands) from the unique values in the CSV.
3. "Unpivots" (melts) the wide week-band columns into long format —
   one row per provider + specialty + period + part-type + band.
4. Loads everything into the MySQL schema created by 01_schema.sql.

Run this after the schema has already been created in MySQL.
"""

import re
import pandas as pd
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------
# Configuration — update these to match your local MySQL setup
# ---------------------------------------------------------------------
DB_USER = "root"
DB_PASSWORD = "optima123!"
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_NAME = "nhs_rtt_analytics"

CSV_PATH = "data/raw/20260430-RTT-April-2026-full-extract.csv"

# ---------------------------------------------------------------------
# Step 1: Connect to MySQL
# ---------------------------------------------------------------------
engine = create_engine(
    f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# ---------------------------------------------------------------------
# Step 2: Read the raw CSV
# ---------------------------------------------------------------------
print("Reading CSV...")
df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
print(f"Loaded {len(df):,} rows, {len(df.columns)} columns")

# ---------------------------------------------------------------------
# Step 2b: Clear existing data so this script is safe to re-run
# (fact table first, since it has foreign keys pointing to the dimensions)
# ---------------------------------------------------------------------
print("Clearing existing data (making this script safe to re-run)...")
with engine.begin() as conn:
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    conn.execute(text("TRUNCATE TABLE fact_rtt_waiting_times"))
    conn.execute(text("TRUNCATE TABLE dim_providers"))
    conn.execute(text("TRUNCATE TABLE dim_commissioners"))
    conn.execute(text("TRUNCATE TABLE dim_treatment_functions"))
    conn.execute(text("TRUNCATE TABLE dim_weeks_bands"))
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
print("  -> All tables cleared")

# ---------------------------------------------------------------------
# Step 3: Identify the week-band columns (everything matching "Gt ... Weeks SUM 1")
# ---------------------------------------------------------------------
band_columns = [c for c in df.columns if re.match(r"^Gt \d+", c)]
print(f"Found {len(band_columns)} week-band columns")

# ---------------------------------------------------------------------
# Step 4: Build the weeks_bands dimension data
# ---------------------------------------------------------------------
def parse_band(col_name):
    two_sided = re.match(r"Gt (\d+) To (\d+) Weeks", col_name)
    if two_sided:
        lower, upper = int(two_sided.group(1)), int(two_sided.group(2))
        label = f"{lower}-{upper} weeks"
        return label, lower, upper
    open_ended = re.match(r"Gt (\d+) Weeks", col_name)
    if open_ended:
        lower = int(open_ended.group(1))
        label = f"{lower}+ weeks"
        return label, lower, None
    raise ValueError(f"Unrecognised band column format: {col_name}")

bands = []
for col in band_columns:
    label, lower, upper = parse_band(col)
    breach_flag = lower >= 18
    bands.append({
        "band_label": label,
        "band_lower": lower,
        "band_upper": upper,
        "breach_flag": breach_flag,
        "_source_column": col,
    })
bands_df = pd.DataFrame(bands)

# ---------------------------------------------------------------------
# Step 5: Load dimension tables first
# ---------------------------------------------------------------------
print("Loading dimension: providers...")
providers = (
    df[["Provider Org Code", "Provider Org Name", "Provider Parent Org Code", "Provider Parent Name"]]
    .drop_duplicates(subset=["Provider Org Code"])
    .rename(columns={
        "Provider Org Code": "provider_code",
        "Provider Org Name": "provider_name",
        "Provider Parent Org Code": "provider_parent_code",
        "Provider Parent Name": "provider_parent_name",
    })
)
providers.to_sql("dim_providers", engine, if_exists="append", index=False,
                  method="multi", chunksize=500)
print(f"  -> {len(providers)} providers loaded")

print("Loading dimension: commissioners...")
commissioners = (
    df[["Commissioner Org Code", "Commissioner Org Name", "Commissioner Parent Org Code", "Commissioner Parent Name"]]
    .dropna(subset=["Commissioner Org Code"])
    .drop_duplicates(subset=["Commissioner Org Code"])
    .rename(columns={
        "Commissioner Org Code": "commissioner_code",
        "Commissioner Org Name": "commissioner_name",
        "Commissioner Parent Org Code": "commissioner_parent_code",
        "Commissioner Parent Name": "commissioner_parent_name",
    })
)
commissioners["commissioner_name"] = commissioners["commissioner_name"].fillna("UNKNOWN / UNSPECIFIED COMMISSIONER")
commissioners.to_sql("dim_commissioners", engine, if_exists="append", index=False,
                      method="multi", chunksize=500)
print(f"  -> {len(commissioners)} commissioners loaded")

print("Loading dimension: treatment functions...")
treatment_functions = (
    df[["Treatment Function Code", "Treatment Function Name"]]
    .drop_duplicates(subset=["Treatment Function Code"])
    .rename(columns={
        "Treatment Function Code": "treatment_function_code",
        "Treatment Function Name": "treatment_function_name",
    })
)
treatment_functions.to_sql("dim_treatment_functions", engine, if_exists="append",
                           index=False, method="multi", chunksize=500)
print(f"  -> {len(treatment_functions)} treatment functions loaded")

print("Loading dimension: weeks bands...")
bands_to_load = bands_df[["band_label", "band_lower", "band_upper", "breach_flag"]]
bands_to_load.to_sql("dim_weeks_bands", engine, if_exists="append", index=False,
                     method="multi", chunksize=500)
print(f"  -> {len(bands_to_load)} week-bands loaded")

band_id_lookup = pd.read_sql("SELECT band_id, band_label FROM dim_weeks_bands", engine)
col_to_band_id = bands_df.merge(band_id_lookup, on="band_label")[["_source_column", "band_id"]] \
    .set_index("_source_column")["band_id"].to_dict()

# ---------------------------------------------------------------------
# Step 6: Unpivot the wide table into long format
# ---------------------------------------------------------------------
print("Unpivoting wide data into long format (this is the main transformation)...")

id_columns = [
    "Period", "Provider Org Code", "Commissioner Org Code",
    "Treatment Function Code", "RTT Part Type",
]

melted = df.melt(
    id_vars=id_columns,
    value_vars=band_columns,
    var_name="_source_column",
    value_name="patient_count",
)

melted = melted[melted["patient_count"].fillna(0) > 0]
melted["band_id"] = melted["_source_column"].map(col_to_band_id)

melted = melted.rename(columns={
    "Period": "period_date",
    "Provider Org Code": "provider_code",
    "Commissioner Org Code": "commissioner_code",
    "Treatment Function Code": "treatment_function_code",
    "RTT Part Type": "rtt_part_type",
})[[
    "period_date", "provider_code", "commissioner_code",
    "treatment_function_code", "rtt_part_type", "band_id", "patient_count",
]]

melted["period_date"] = pd.to_datetime(
    melted["period_date"].str.replace("RTT-", "", regex=False),
    format="%B-%Y",
).dt.date

print(f"  -> {len(melted):,} fact rows to load (after dropping zero-count rows)")

# ---------------------------------------------------------------------
# Step 7: Load the fact table
# ---------------------------------------------------------------------
print("Loading fact table (this is the biggest step, may take a few minutes)...")
melted.to_sql("fact_rtt_waiting_times", engine, if_exists="append", index=False,
              method="multi", chunksize=2000)

print("Done! Data load complete.")

# ---------------------------------------------------------------------
# Step 8: Quick sanity check
# ---------------------------------------------------------------------
with engine.connect() as conn:
    counts = conn.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM dim_providers) AS providers,
            (SELECT COUNT(*) FROM dim_commissioners) AS commissioners,
            (SELECT COUNT(*) FROM dim_treatment_functions) AS treatment_functions,
            (SELECT COUNT(*) FROM dim_weeks_bands) AS weeks_bands,
            (SELECT COUNT(*) FROM fact_rtt_waiting_times) AS fact_rows
    """)).fetchone()
    print(f"""
Final row counts:
  Providers:            {counts[0]:,}
  Commissioners:         {counts[1]:,}
  Treatment functions:   {counts[2]:,}
  Weeks bands:           {counts[3]:,}
  Fact rows:             {counts[4]:,}
""")