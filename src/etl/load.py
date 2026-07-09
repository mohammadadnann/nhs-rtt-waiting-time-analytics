"""
Load stage

This is the only file that talks to the database. Extract and transform
never open a database connection, so if I ever needed to load this data
somewhere other than MySQL, this is the only file I would need to change.
"""

import pandas as pd
from sqlalchemy import create_engine, text

from src.config import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME


def get_engine():
    connection_string = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(connection_string)


def get_loaded_periods(engine):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT DISTINCT period_date FROM fact_rtt_waiting_times"))
        rows = result.fetchall()
    return {row[0] for row in rows}


def load_band_reference(engine, bands_df):
    existing = pd.read_sql("SELECT band_id, band_label FROM dim_weeks_bands", engine)

    if len(existing) > 0:
        lookup = bands_df.merge(existing, on="band_label")
        return lookup.set_index("source_column")["band_id"].to_dict()

    columns_to_load = bands_df[["band_label", "band_lower", "band_upper", "breach_flag"]]
    columns_to_load.to_sql("dim_weeks_bands", engine, if_exists="append", index=False, method="multi")

    band_id_lookup = pd.read_sql("SELECT band_id, band_label FROM dim_weeks_bands", engine)
    merged = bands_df.merge(band_id_lookup, on="band_label")
    return merged.set_index("source_column")["band_id"].to_dict()


def load_dimension_rows(engine, dimension_df, table_name, key_column):
    existing_codes = pd.read_sql(f"SELECT {key_column} FROM {table_name}", engine)[key_column]
    new_rows = dimension_df[~dimension_df[key_column].isin(existing_codes)]

    if len(new_rows) > 0:
        new_rows.to_sql(table_name, engine, if_exists="append", index=False, method="multi")

    return len(new_rows)


def load_fact_rows(engine, fact_df):
    fact_df.to_sql("fact_rtt_waiting_times", engine, if_exists="append", index=False,
                    method="multi", chunksize=5000)
    return len(fact_df)