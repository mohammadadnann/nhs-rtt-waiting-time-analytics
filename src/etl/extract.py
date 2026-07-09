"""
Extract stage

This file only reads files from disk. It does not clean or reshape
anything, that happens in transform.py instead.
"""

import re

import pandas as pd

from src.config import RAW_DATA_DIR


def list_raw_files():
    return sorted(RAW_DATA_DIR.glob("*-full-extract.csv"))


def read_csv_file(csv_path):
    return pd.read_csv(csv_path, encoding="utf-8-sig")


def get_period_date(csv_path):
    first_row = pd.read_csv(csv_path, encoding="utf-8-sig", usecols=["Period"], nrows=1)
    period_text = first_row["Period"].iloc[0].replace("RTT-", "")
    return pd.to_datetime(period_text, format="%B-%Y").date()


def get_band_columns(csv_path):
    sample = pd.read_csv(csv_path, encoding="utf-8-sig", nrows=5)
    band_columns = []
    for col in sample.columns:
        if re.match(r"^Gt \d+", col):
            band_columns.append(col)
    return band_columns