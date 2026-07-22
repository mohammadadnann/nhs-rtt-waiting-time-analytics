"""
Pipeline orchestration


Calls extract, then transform, then load, for every new monthly file
sitting in data/raw. Already loaded months are skipped, so it is always
safe to rerun this.
"""

from src.etl import extract, transform, load


def run_pipeline():
    csv_files = extract.list_raw_files()

    if not csv_files:
        print("No raw files found in data/raw. Nothing to do.")
        return

    engine = load.get_engine()
    loaded_periods = load.get_loaded_periods(engine)
    print(f"Found {len(csv_files)} raw file(s), {len(loaded_periods)} month(s) already loaded")

    # the week band structure is the same in every file, so I only need
    # to read it from the first file
    band_columns = extract.get_band_columns(csv_files[0])
    bands_df = transform.build_band_reference(band_columns)
    band_id_lookup = load.load_band_reference(engine, bands_df)
    print(f"Week band lookup ready, {len(band_id_lookup)} bands")

    for csv_path in csv_files:
        period_date = extract.get_period_date(csv_path)

        if period_date in loaded_periods:
            print(f"\nSkipping {csv_path.name}, {period_date} already loaded")
            continue

        print(f"\nProcessing {csv_path.name} ...")

        raw_df = extract.read_csv_file(csv_path)
        print(f"  Read {len(raw_df):,} rows")

        clean_df = transform.remove_total_rows(raw_df)
        print(f"  Removed {len(raw_df) - len(clean_df):,} C_999 total rollup rows")

        providers = transform.get_unique_providers(clean_df)
        commissioners = transform.get_unique_commissioners(clean_df)
        treatment_functions = transform.get_unique_treatment_functions(clean_df)
        fact_rows = transform.reshape_to_long_format(clean_df, band_columns, band_id_lookup)
        print(f"  Reshaped into {len(fact_rows):,} long format rows")

        new_providers = load.load_dimension_rows(engine, providers, "dim_providers", "provider_code")
        new_commissioners = load.load_dimension_rows(engine, commissioners, "dim_commissioners", "commissioner_code")
        new_treatment_functions = load.load_dimension_rows(engine, treatment_functions, "dim_treatment_functions", "treatment_function_code")
        load.load_fact_rows(engine, fact_rows)

        print(f"  Loaded. New providers: {new_providers}, new commissioners: {new_commissioners}, "
              f"new treatment functions: {new_treatment_functions}")

    print("\nPipeline run complete.")


if __name__ == "__main__":
    run_pipeline()