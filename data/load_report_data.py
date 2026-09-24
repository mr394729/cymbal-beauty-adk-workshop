"""Plan or apply only the two additive end-of-day analytics feeds with keyed MERGE.

Default is read-only planning. --apply creates missing report tables and upserts
only fixture keys; it never reloads, deletes or modifies an operational table.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.cymbal_store_ops.reporting_fixtures import (
    PRODUCTS,
    REPORT_TABLE_COUNTS,
    generate_report_tables,
)

KEYS = {
    "pos_daily_product_sales": ("store_id", "business_date", "product_id"),
    "worked_shifts": ("store_id", "business_date", "associate_id", "clock_in"),
}
SCHEMAS = Path(__file__).parent / "schemas"


def checked_target(project, namespace):
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project):
        raise ValueError("A valid explicit Google Cloud project ID is required.")
    if not re.fullmatch(r"[a-z][a-z0-9]{2,11}", namespace):
        raise ValueError("Namespace must contain 3–12 lowercase letters/digits.")
    return f"{project}.cymbal_beauty_{namespace}_dev"


def schema_for(name):
    if name not in KEYS:
        raise ValueError("Only the two reporting tables are supported.")
    return json.loads((SCHEMAS / f"{name}.json").read_text())


def merge_sql(dataset, name):
    schema = schema_for(name)
    columns = [f["name"] for f in schema]
    projection = ", ".join(
        f"CAST(JSON_VALUE(row, '$.{f['name']}') AS {f['type']}) AS {f['name']}" for f in schema
    )
    source = f"SELECT {projection} FROM UNNEST(JSON_QUERY_ARRAY(@rows)) AS row"
    join = " AND ".join(f"target.{k}=source.{k}" for k in KEYS[name])
    updates = ", ".join(f"{c}=source.{c}" for c in columns if c not in KEYS[name])
    return f"MERGE `{dataset}.{name}` target USING ({source}) source ON {join} WHEN MATCHED THEN UPDATE SET {updates} WHEN NOT MATCHED THEN INSERT ({', '.join(columns)}) VALUES ({', '.join('source.' + c for c in columns)})"


def main(argv=None):
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--location", default="US")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    dataset = checked_target(args.project, args.namespace)
    client = bigquery.Client(project=args.project, location=args.location)
    info = client.get_dataset(dataset)
    if (
        info.location.upper() != args.location.upper()
        or (info.labels or {}).get("ns") != args.namespace
        or (info.labels or {}).get("env") != "dev"
    ):
        raise ValueError(
            "Dataset location/namespace/environment labels do not match the requested dev target."
        )
    labels = {"ns": args.namespace, "env": "dev", "component": "end_of_day"}

    def config(params=None, dry=False):
        return bigquery.QueryJobConfig(
            query_parameters=params or [],
            maximum_bytes_billed=104857600,
            labels=labels,
            dry_run=dry,
            use_query_cache=not dry,
        )

    # Read actual existing bounded source records before constructing the new feeds.
    # Manager-first ordering matches the fixed local generator's roster order.
    source_sql = f"""SELECT TO_JSON_STRING(STRUCT(
      ARRAY(SELECT AS STRUCT product_id,price_usd FROM `{dataset}.products` WHERE product_id IN UNNEST(@products)) AS products,
      ARRAY(SELECT AS STRUCT associate_id,store_id,role FROM `{dataset}.associates` WHERE store_id='S-014' AND role!='district_manager' ORDER BY IF(role='store_manager',0,1),associate_id) AS associates,
      ARRAY(SELECT AS STRUCT store_id,ts_hour,sales_usd FROM `{dataset}.store_traffic` WHERE store_id='S-014'
        AND ts_hour>=TIMESTAMP('2026-10-01','America/Chicago') AND ts_hour<TIMESTAMP('2026-10-03','America/Chicago') ORDER BY ts_hour) AS store_traffic
    )) AS source_json"""
    params = [bigquery.ArrayQueryParameter("products", "STRING", list(PRODUCTS))]
    source_dry = client.query(source_sql, job_config=config(params, True))
    source_dry.result()
    rows = list(client.query(source_sql, job_config=config(params)).result())
    source = json.loads(rows[0]["source_json"])
    if len(source["products"]) != 20 or len(source["store_traffic"]) != 24:
        raise ValueError("Report fixture sources are incomplete; nothing written.")
    feeds = generate_report_tables(source)
    plan = {
        "target": dataset,
        "location": args.location,
        "apply": args.apply,
        "source_bytes": source_dry.total_bytes_processed,
        "tables": {},
    }
    existing = {}
    for name, records in feeds.items():
        try:
            table = client.get_table(f"{dataset}.{name}")
        except NotFound:
            table = None
        if table is not None:
            expected = [(f["name"], f["type"], f["mode"]) for f in schema_for(name)]
            actual = [
                (f.name, {"INTEGER": "INT64"}.get(f.field_type, f.field_type), f.mode)
                for f in table.schema
            ]
            if expected != actual or any(
                (table.labels or {}).get(k) != v for k, v in labels.items()
            ):
                raise ValueError(
                    f"Existing {name} is not a matching report-owned table; nothing written."
                )
        existing[name] = table
        plan["tables"][name] = {
            "exists": table is not None,
            "fixture_rows": len(records),
            "merge_keys": KEYS[name],
            "existing_rows": table.num_rows if table else 0,
        }
    # Dry-run mode does not create a staging table, dataset, or target table.
    for name, records in feeds.items():
        if args.apply and existing[name] is None:
            table = bigquery.Table(
                f"{dataset}.{name}",
                schema=[bigquery.SchemaField.from_api_repr(f) for f in schema_for(name)],
            )
            table.labels = labels
            table.description = (
                "Cymbal Beauty historical end-of-day reporting fixture; additive reporting feed."
            )
            client.create_table(table)
            existing[name] = table
        if existing[name] is not None:
            params = [bigquery.ScalarQueryParameter("rows", "STRING", json.dumps(records))]
            sql = merge_sql(dataset, name)
            dry = client.query(sql, job_config=config(params, True))
            dry.result()
            plan["tables"][name]["merge_bytes"] = dry.total_bytes_processed
            if args.apply:
                job = client.query(sql, job_config=config(params))
                job.result()
                plan["tables"][name]["affected_rows"] = job.num_dml_affected_rows
                verification = list(
                    client.query(
                        f"SELECT COUNT(*) AS n, COUNT(DISTINCT TO_JSON_STRING(STRUCT({', '.join(KEYS[name])}))) AS keys FROM `{dataset}.{name}` WHERE store_id='S-014' AND business_date IN (DATE('2026-10-01'),DATE('2026-10-02'))",
                        job_config=config(),
                    ).result()
                )[0]
                if (
                    verification["n"] != REPORT_TABLE_COUNTS[name]
                    or verification["keys"] != REPORT_TABLE_COUNTS[name]
                ):
                    raise ValueError(f"Post-MERGE verification failed for {name}.")
                plan["tables"][name]["verified_rows"] = verification["n"]
        else:
            plan["tables"][name]["merge_validation"] = (
                "requires creation of this new table during --apply"
            )
    text = json.dumps(plan, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
