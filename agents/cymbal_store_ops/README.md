# Inside the store agent

[Agent overview](../README.md) · [Architecture walkthrough](../../docs/ARCHITECTURE.md)

The coordinator answers store questions using tools and specialist agents. Tools supply records and enforce
access. The model chooses relevant reads, interprets evidence and proposes useful next actions.

| Area | Responsibility |
|---|---|
| [agent.py](agent.py) | Build the coordinator and resumable ADK application |
| [sub_agents](sub_agents/README.md) | Specialist consultation, coaching, task handling and the briefing workflow |
| [tools](tools/README.md) | Queries, domain calculations, reports and confirmed writes |
| [prompts](prompts/README.md) | Instructions for evidence use, communication and scope |
| [config](config/README.md) | Environment configuration and loading |
| [callbacks.py](callbacks.py), [plugins.py](plugins.py) | Access boundaries, redaction and execution limits |
| [chat_reply.py](chat_reply.py), [context_history.py](context_history.py) | User-facing answers, follow-up activities and model context |
| [trace.py](trace.py) | Recorded agent, model and tool spans |

The briefing is a fixed read workflow with one model synthesis. Other questions are handled through the
available capabilities; scenario chips provide example requests, not response templates.

Use `uv run adk web agents --port 8000` for ADK's developer UI or `uv run python frontend/server.py --target local --port 8080` for the tablet experience after cloud setup.
Developer invariants live in [AGENTS.md](AGENTS.md).
