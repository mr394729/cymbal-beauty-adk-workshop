# Operational tools

[Application](../README.md) · [Notebook 03](../../../notebooks/03_tools_and_workflows.ipynb)

Tools expose business data and bounded actions. They do not select a canned answer from the user's question.

![Query and report flow](../../../docs/diagrams/query-report.png)

| Tool group | Source | Purpose |
|---|---|---|
| Flexible reads | [store_query.py](store_query.py) | Discover fields; filter, group, aggregate, sort and page nine resources |
| Inventory | [inventory_summary.py](inventory_summary.py), [inventory_context.py](inventory_context.py) | Whole-store summaries and product-level evidence |
| Operational context | [operations_tools.py](operations_tools.py), [pickup_workload.py](pickup_workload.py) | Coverage, reservations, controls and workload calculations |
| Personal work | [personal_tools.py](personal_tools.py) | Own tasks, development and confirmed task updates |
| Domain operations | [domain_tools.py](domain_tools.py) | Product, stock, task and other shared capabilities |
| Reports | [report_delivery.py](report_delivery.py) | Deliver searchable rows and CSV data to the UI |
| Procedures | [policy_lookup.py](policy_lookup.py) | Optional retrieval from a configured SOP data store |
| Storage | [data_backend.py](data_backend.py), [backends](backends/) | Shared contract, BigQuery implementation and local test backend |
| SQL boundary | [sql_guard.py](sql_guard.py) | Read-only and allowed-dataset checks |

Queries enforce store, role and ownership in code. Report rows go to UI state with counts and completeness;
the model receives metadata instead of thousands of rows. Task writes require separate confirmation.
