"""
NHS England RTT Waiting Times, data loading script
Project: NHS RTT SQL Driven Business Analytics and Breach Risk Forecasting

This script reads every raw NHS RTT full extract CSV sitting in data/raw,
reshapes each one from wide format (one column per waiting time week band)
into the long format the star schema expects, and loads it into MySQL.

Unlike the first version of this script, this one does not truncate the
database on every run. It checks which period_dates are already loaded and
skips those files, so I can drop a new month's CSV into data/raw and rerun
this script without reprocessing everything that is already in. Dimension
rows (providers, commissioners, treatment functions, week bands) are only
inserted if they are not already present, since the same provider or
specialty code shows up again in every month's file.
"""

import re
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

DB_USER = "root"
DB_PASSWORD = "optima123!"
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_NAME = "nhs_rtt_analytics"

RAW_DATA_DIR = Path("data/raw")

engine = create_engine(
    f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)


def get_loaded_periods():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT period_date FROM fact_rtt_waiting_times")).fetchall()
    return {row[0] for row in rows}


def parse_band(col_name):
    two_sided = re.match(r"Gt (\d+) To (\d+) Weeks", col_name)
    if two_sided:
        lower, upper = int(two_sided.group(1)), int(two_sided.group(2))
        return f"{lower} to {upper} weeks", lower, upper
    open_ended = re.match(r"Gt (\d+) Weeks", col_name)
    if open_ended:
        lower = int(open_ended.group(1))
        return f"{lower} plus weeks", lower, None
    raise ValueError(f"Column name did not match the expected band format: {col_name}")


def ensure_week_bands_loaded(band_columns):
    existing = pd.read_sql("SELECT band_id, band_label FROM dim_weeks_bands", engine)
    if len(existing) > 0:
        label_to_source = {}
        for col in band_columns:
            label, _, _ = parse_band(col)
            label_to_source[label] = col
        existing["_source_column"] = existing["band_label"].map(label_to_source)
        return existing.set_index("_source_column")["band_id"].to_dict()

    bands = []
    for col in band_columns:
        label, lower, upper = parse_band(col)
        bands.append({
            "band_label": label,
            "band_lower": lower,
            "band_upper": upper,
            "breach_flag": lower >= 18,
            "_source_column": col,
        })
    bands_df = pd.DataFrame(bands)
    bands_df[["band_label", "band_lower", "band_upper", "breach_flag"]].to_sql(
        "dim_weeks_bands", engine, if_exists="append", index=False, method="multi", chunksize=500
    )
    band_id_lookup = pd.read_sql("SELECT band_id, band_label FROM dim_weeks_bands", engine)
    return bands_df.merge(band_id_lookup, on="band_label").set_index("_source_column")["band_id"].to_dict()


def upsert_dimension(df, table, key_col, rename_map, fillna_map=None):
    subset = df[list(rename_map.keys())].drop_duplicates(subset=[key_col]).rename(columns=rename_map)
    if fillna_map:
        for col, value in fillna_map.items():
            subset[col] = subset[col].fillna(value)
    db_key_col = rename_map[key_col]
    existing_codes = pd.read_sql(f"SELECT {db_key_col} FROM {table}", engine)[db_key_col]
    new_rows = subset[~subset[db_key_col].isin(existing_codes)]
    if len(new_rows) > 0:
        new_rows.to_sql(table, engine, if_exists="append", index=False, method="multi", chunksize=500)
    return len(new_rows)


def process_file(csv_path, col_to_band_id):
    print(f"\nReading {csv_path.name} ...")
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    print(f"  {len(df):,} rows, {len(df.columns)} columns")

    before = len(df)
    df = df[df["Treatment Function Code"] != "C_999"]
    print(f"  Dropped {before - len(df):,} C_999 total rollup rows")

    new_providers = upsert_dimension(
        df, "dim_providers", "Provider Org Code",
        {
            "Provider Org Code": "provider_code",
            "Provider Org Name": "provider_name",
            "Provider Parent Org Code": "provider_parent_code",
            "Provider Parent Name": "provider_parent_name",
        },
    )
    print(f"  Added {new_providers} new providers")

    new_commissioners = upsert_dimension(
        df.dropna(subset=["Commissioner Org Code"]), "dim_commissioners", "Commissioner Org Code",
        {
            "Commissioner Org Code": "commissioner_code",
            "Commissioner Org Name": "commissioner_name",
            "Commissioner Parent Org Code": "commissioner_parent_code",
            "Commissioner Parent Name": "commissioner_parent_name",
        },
        fillna_map={"commissioner_name": "UNKNOWN OR UNSPECIFIED COMMISSIONER"},
    )
    print(f"  Added {new_commissioners} new commissioners")

    new_treatment_functions = upsert_dimension(
        df, "dim_treatment_functions", "Treatment Function Code",
        {
            "Treatment Function Code": "treatment_function_code",
            "Treatment Function Name": "treatment_function_name",
        },
    )
    print(f"  Added {new_treatment_functions} new treatment functions")

    id_columns = ["Period", "Provider Org Code", "Commissioner Org Code",
                  "Treatment Function Code", "RTT Part Type"]
    band_columns = list(col_to_band_id.keys())

    melted = df.melt(id_vars=id_columns, value_vars=band_columns,
                      var_name="_source_column", value_name="patient_count")
    melted = melted[melted["patient_count"].fillna(0) > 0]
    melted["band_id"] = melted["_source_column"].map(col_to_band_id)

    melted = melted.rename(columns={
        "Period": "period_date",
        "Provider Org Code": "provider_code",
        "Commissioner Org Code": "commissioner_code",
        "Treatment Function Code": "treatment_function_code",
        "RTT Part Type": "rtt_part_type",
    })[["period_date", "provider_code", "commissioner_code",
        "treatment_function_code", "rtt_part_type", "band_id", "patient_count"]]

    melted["period_date"] = pd.to_datetime(
        melted["period_date"].str.replace("RTT-", "", regex=False), format="%B-%Y"
    ).dt.date

    print(f"  {len(melted):,} fact rows ready to load")
    melted.to_sql("fact_rtt_waiting_times", engine, if_exists="append", index=False,
                  method="multi", chunksize=5000)
    print(f"  Loaded {csv_path.name}")


def main():
    csv_files = sorted(RAW_DATA_DIR.glob("*-full-extract.csv"))
    if not csv_files:
        print(f"No full extract CSVs found in {RAW_DATA_DIR}. Nothing to do.")
        return

    loaded_periods = get_loaded_periods()
    print(f"Found {len(csv_files)} raw file(s), {len(loaded_periods)} period(s) already loaded")

    sample_df = pd.read_csv(csv_files[0], encoding="utf-8-sig", nrows=5)
    band_columns = [c for c in sample_df.columns if re.match(r"^Gt \d+", c)]
    col_to_band_id = ensure_week_bands_loaded(band_columns)
    print(f"Week band lookup ready, {len(col_to_band_id)} bands")

    for csv_path in csv_files:
        peek = pd.read_csv(csv_path, encoding="utf-8-sig", usecols=["Period"], nrows=1)
        period_text = peek["Period"].iloc[0].replace("RTT-", "")
        period_date = pd.to_datetime(period_text, format="%B-%Y").date()
        if period_date in loaded_periods:
            print(f"\nSkipping {csv_path.name}, {period_date} already loaded")
            continue
        process_file(csv_path, col_to_band_id)

    with engine.connect() as conn:
        counts = conn.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM dim_providers) AS providers,
                (SELECT COUNT(*) FROM dim_commissioners) AS commissioners,
                (SELECT COUNT(*) FROM dim_treatment_functions) AS treatment_functions,
                (SELECT COUNT(*) FROM dim_weeks_bands) AS weeks_bands,
                (SELECT COUNT(*) FROM fact_rtt_waiting_times) AS fact_rows,
                (SELECT COUNT(DISTINCT period_date) FROM fact_rtt_waiting_times) AS months_loaded
        """)).fetchone()
        print(f"""
Final totals:
  Providers:            {counts[0]:,}
  Commissioners:        {counts[1]:,}
  Treatment functions:  {counts[2]:,}
  Week bands:           {counts[3]:,}
  Fact rows:            {counts[4]:,}
  Months loaded:        {counts[5]}
""")


if __name__ == "__main__":
    main()