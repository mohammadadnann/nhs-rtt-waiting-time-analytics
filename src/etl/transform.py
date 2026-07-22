"""
Transform stage

This file cleans the raw data and reshapes it from wide format into the
long format the fact table needs. Nothing here touches the database.
"""

import re

import pandas as pd


def parse_band_name(col_name):
    # turns "Gt 13 To 14 Weeks" into a label plus lower and upper bounds
    two_sided = re.match(r"Gt (\d+) To (\d+) Weeks", col_name)
    if two_sided:
        lower = int(two_sided.group(1))
        upper = int(two_sided.group(2))
        return f"{lower} to {upper} weeks", lower, upper

    open_ended = re.match(r"Gt (\d+) Weeks", col_name)
    lower = int(open_ended.group(1))
    return f"{lower} plus weeks", lower, None


def build_band_reference(band_columns):
    # builds one row per week band, with the breach flag set to True for
    # any band starting at 18 weeks or later, the RTT standard
    rows = []
    for col in band_columns:
        label, lower, upper = parse_band_name(col)
        rows.append({
            "band_label": label,
            "band_lower": lower,
            "band_upper": upper,
            "breach_flag": lower >= 18,
            "source_column": col,
        })
    return pd.DataFrame(rows)


def remove_total_rows(df):
    # drops the C_999 Total rows, which just sum the real specialty rows
    # in each group, so keeping them would double count every patient
    return df[df["Treatment Function Code"] != "C_999"].copy()


def get_unique_providers(df):
    columns = ["Provider Org Code", "Provider Org Name",
               "Provider Parent Org Code", "Provider Parent Name"]
    providers = df[columns].drop_duplicates(subset=["Provider Org Code"])
    providers = providers.rename(columns={
        "Provider Org Code": "provider_code",
        "Provider Org Name": "provider_name",
        "Provider Parent Org Code": "provider_parent_code",
        "Provider Parent Name": "provider_parent_name",
    })
    return providers


def get_unique_commissioners(df):
    df = df.dropna(subset=["Commissioner Org Code"])
    columns = ["Commissioner Org Code", "Commissioner Org Name",
               "Commissioner Parent Org Code", "Commissioner Parent Name"]
    commissioners = df[columns].drop_duplicates(subset=["Commissioner Org Code"])
    commissioners = commissioners.rename(columns={
        "Commissioner Org Code": "commissioner_code",
        "Commissioner Org Name": "commissioner_name",
        "Commissioner Parent Org Code": "commissioner_parent_code",
        "Commissioner Parent Name": "commissioner_parent_name",
    })
    commissioners["commissioner_name"] = commissioners["commissioner_name"].fillna("UNKNOWN OR UNSPECIFIED COMMISSIONER")
    return commissioners


def get_unique_treatment_functions(df):
    columns = ["Treatment Function Code", "Treatment Function Name"]
    treatment_functions = df[columns].drop_duplicates(subset=["Treatment Function Code"])
    treatment_functions = treatment_functions.rename(columns={
        "Treatment Function Code": "treatment_function_code",
        "Treatment Function Name": "treatment_function_name",
    })
    return treatment_functions


def reshape_to_long_format(df, band_columns, band_id_lookup):
    # turns the wide file, one column per week band, into one row per
    # provider, commissioner, specialty, part type, and band
    id_columns = ["Period", "Provider Org Code", "Commissioner Org Code",
                  "Treatment Function Code", "RTT Part Type"]

    long_df = df.melt(id_vars=id_columns, value_vars=band_columns,
                       var_name="source_column", value_name="patient_count")

    # no point keeping a row where nobody was waiting in that band
    long_df = long_df[long_df["patient_count"].fillna(0) > 0]

    long_df["band_id"] = long_df["source_column"].map(band_id_lookup)

    long_df = long_df.rename(columns={
        "Period": "period_date",
        "Provider Org Code": "provider_code",
        "Commissioner Org Code": "commissioner_code",
        "Treatment Function Code": "treatment_function_code",
        "RTT Part Type": "rtt_part_type",
    })

    long_df = long_df[["period_date", "provider_code", "commissioner_code",
                        "treatment_function_code", "rtt_part_type", "band_id", "patient_count"]]

    period_text = long_df["period_date"].str.replace("RTT-", "", regex=False)
    long_df["period_date"] = pd.to_datetime(period_text, format="%B-%Y").dt.date

    return long_df