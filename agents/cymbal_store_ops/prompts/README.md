# Agent instructions

[Application](../README.md) · [Evaluation guide](../../../eval/README.md)

Markdown files define each agent's purpose, evidence rules and communication style. The prompt loader
substitutes environment values while preserving ADK session-state references.

Instructions should explain capabilities and constraints, leaving the model to choose relevant tools for
open-ended requests. The morning briefing deliberately uses a fixed read workflow before synthesis.
Access checks, confirmation and database limits are enforced in code rather than relying on these instructions.

After a behavior change, run the relevant factual and multi-turn evaluations as well as unit tests.
