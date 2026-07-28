"""
Landing-zone loader: reads the raw parquet files (stand-in for whatever
lands them in a real deployment — S3 + Snowpipe, a Flink sink, etc.) into
the DuckDB warehouse dbt's sources.yml points at.

Run before `dbt run`:
    python load_raw.py
"""
import duckdb

RAW_DIR = "../../../data/raw"
WAREHOUSE = "../../../data/warehouse.duckdb"

TABLES = ["users", "subscription_events", "ad_clicks", "dim_advertisers"]


def main():
    con = duckdb.connect(WAREHOUSE)
    for table in TABLES:
        con.execute(
            f"create or replace table {table} as "
            f"select * from read_parquet('{RAW_DIR}/{table}.parquet')"
        )
        n = con.execute(f"select count(*) from {table}").fetchone()[0]
        print(f"loaded {table}: {n:,} rows")
    con.close()


if __name__ == "__main__":
    main()
