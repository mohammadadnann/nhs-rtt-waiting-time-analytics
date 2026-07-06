"""
NHS England RTT Waiting Times, data loading script
Project: NHS RTT SQL Driven Business Analytics and Breach Risk Forecasting

This script reads the raw NHS RTT extract, which is stored in wide format
with one column per waiting time week band. I reshape it into a long
format that fits the star schema created by 01_schema.sql, then load it
into MySQL. Run this after the schema already exists in the database.
"""

import re
import pandas as pd
from sqlalchemy import create_engine, text

# Database connection settings, update these to match your local MySQL setup
DB_USER = "root"
DB_PASSWORD = "optima123!"
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_NAME = "nhs_rtt_analytics"

CSV_PATH = "data/raw/20260430-RTT-April-2026-full-extract.csv"

engine = create_engine(
    f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

print("Reading CSV...")
df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
print(f"Loaded {len(df):,} rows, {len(df.columns)} columns")

# Each provider, commissioner, and part type group has an extra row where the
# code is C_999 and the name is Total. This row is just the sum of the real
# specialty rows in that same group. If I keep it, every patient count gets
# added twice, once under their real specialty and once again in this Total
# row. So I remove these rows before doing anything else.
before_count = len(df)
df = df[df["Treatment Function Code"] != "C_999"]
print(f"Dropped {before_count - len(df):,} C_999 total rollup rows")

# I clear all tables first so this script can be run again without hitting
# duplicate key errors. The fact table is cleared before the dimension tables
# since it holds foreign keys pointing to them.
print("Clearing existing data so this script is safe to run again...")
with engine.begin() as conn:
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    conn.execute(text("TRUNCATE TABLE fact_rtt_waiting_times"))
    conn.execute(text("TRUNCATE TABLE dim_providers"))
    conn.execute(text("TRUNCATE TABLE dim_commissioners"))
    conn.execute(text("TRUNCATE TABLE dim_treatment_functions"))
    conn.execute(text("TRUNCATE TABLE dim_weeks_bands"))
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
print("All tables cleared")

# The week band columns are named like Gt 00 To 01 Weeks SUM 1, so I find
# them by matching that pattern rather than listing all 105 by hand.
band_columns = [c for c in df.columns if re.match(r"^Gt \d+", c)]
print(f"Found {len(band_columns)} week band columns")

def parse_band(col_name):
    # Turns a column name like Gt 13 To 14 Weeks into a label and the lower
    # and upper bounds in weeks. Some bands are open ended, like Gt 104
    # Weeks, which has no upper bound, so upper stays None for those.
    two_sided = re.match(r"Gt (\d+) To (\d+) Weeks", col_name)
    if two_sided:
        lower, upper = int(two_sided.group(1)), int(two_sided.group(2))
        label = f"{lower} to {upper} weeks"
        return label, lower, upper
    open_ended = re.match(r"Gt (\d+) Weeks", col_name)
    if open_ended:
        lower = int(open_ended.group(1))
        label = f"{lower} plus weeks"
        return label, lower, None
    raise ValueError(f"Column name did not match the expected band format: {col_name}")

bands = []
for col in band_columns:
    label, lower, upper = parse_band(col)
    # The RTT standard is 18 weeks, so any band starting at 18 or later
    # counts as a breach.
    breach_flag = lower >= 18
    bands.append({
        "band_label": label,
        "band_lower": lower,
        "band_upper": upper,
        "breach_flag": breach_flag,
        "_source_column": col,
    })
bands_df = pd.DataFrame(bands)

print("Loading providers...")
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
print(f"Loaded {len(providers)} providers")

print("Loading commissioners...")
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
# A few commissioner codes in the raw data have no name recorded, for
# example legacy codes like Y56 and Y58. I fill these in with a clear
# placeholder rather than letting the load fail on the NOT NULL constraint.
commissioners["commissioner_name"] = commissioners["commissioner_name"].fillna("UNKNOWN OR UNSPECIFIED COMMISSIONER")
commissioners.to_sql("dim_commissioners", engine, if_exists="append", index=False,
                      method="multi", chunksize=500)
print(f"Loaded {len(commissioners)} commissioners")

print("Loading treatment functions...")
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
print(f"Loaded {len(treatment_functions)} treatment functions")

print("Loading week bands...")
bands_to_load = bands_df[["band_label", "band_lower", "band_upper", "breach_flag"]]
bands_to_load.to_sql("dim_weeks_bands", engine, if_exists="append", index=False,
                     method="multi", chunksize=500)
print(f"Loaded {len(bands_to_load)} week bands")

# MySQL assigns the band_id values automatically when the rows above are
# inserted, so I read them back here to build a lookup from column name to
# band_id, which I need for the next step.
band_id_lookup = pd.read_sql("SELECT band_id, band_label FROM dim_weeks_bands", engine)
col_to_band_id = bands_df.merge(band_id_lookup, on="band_label")[["_source_column", "band_id"]] \
    .set_index("_source_column")["band_id"].to_dict()

print("Reshaping the wide data into one row per band...")
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

# I drop rows with a zero or missing patient count, since there is nothing
# to store for a band nobody was waiting in.
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

# The Period column comes in as text like RTT-April-2026, so I strip the
# RTT prefix and parse the rest as a month and year to get a real date.
melted["period_date"] = pd.to_datetime(
    melted["period_date"].str.replace("RTT-", "", regex=False),
    format="%B-%Y",
).dt.date

print(f"{len(melted):,} rows ready to load into the fact table")

print("Loading the fact table, this is the biggest step and may take a few minutes...")
melted.to_sql("fact_rtt_waiting_times", engine, if_exists="append", index=False,
              method="multi", chunksize=2000)

print("Done, data load complete")

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
  Commissioners:        {counts[1]:,}
  Treatment functions:  {counts[2]:,}
  Week bands:           {counts[3]:,}
  Fact rows:            {counts[4]:,}
""")