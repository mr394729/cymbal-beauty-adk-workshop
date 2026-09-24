# Store operations application

[Workshop home](../README.md) · [Notebook 02](../notebooks/02_agent_patterns.ipynb) · [Architecture](../docs/ARCHITECTURE.md)

The [cymbal_store_ops](cymbal_store_ops/README.md) package is the running ADK application. It combines general
store-data tools with specialist analysis and reviewed task actions.

![Agent composition](../docs/diagrams/store-agent-architecture.png)

Start with [agent.py](cymbal_store_ops/agent.py) to see the capabilities registered on the coordinator.
The notebook constructs this factory and shows the resulting tree, so the walkthrough follows the source.
