"""
Config loader
Project: NHS RTT SQL Driven Business Analytics and Breach Risk Forecasting

Every other file in this project imports its settings from here instead
of typing them out directly. Secrets, like the database password, come
from .env, which is gitignored. Non secret settings, like folder paths,
come from config.yaml, which is committed since there is nothing private
in it.
"""

from pathlib import Path

import yaml
from dotenv import load_dotenv
import os

load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")

with open("config.yaml") as f:
    _settings = yaml.safe_load(f)

DB_NAME = _settings["database"]["name"]
RAW_DATA_DIR = Path(_settings["paths"]["raw_data_dir"])
REFERENCE_DATA_DIR = Path(_settings["paths"]["reference_data_dir"])
REGION_LOOKUP_FILE = Path(_settings["paths"]["region_lookup_file"])