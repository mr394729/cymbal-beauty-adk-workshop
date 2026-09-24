# Implementation status

[Documentation](README.md) · [Repository QA](REPOSITORY_QA.md)

This is a maintainer reference, separate from the attendee walkthrough. A design document or standalone
quickstart is not evidence that the same capability is integrated into the tablet application.

| Capability | Repository status | Remaining integration |
|---|---|---|
| PDF daily dashboard | Local design and artifact API exploration only | Store-agent tool, template/data integration, saved artifact, authenticated PDF viewer and deployed test |
| Event notifications | Standalone recommendation publisher and [design](patterns/event-alerts.md) | Inbound event worker, deduplication, agent invocation, inbox/badge and chat entry |
| Hosted MCP | Local stdio quickstart and [design](patterns/mcp-service.md) | Authenticated Cloud Run service, runtime connection, registration and deployment tests |
| SOP retrieval | Optional tool and setup quickstart | Configure and test the selected namespace's search data store |
| Long-term memory | Standalone memory quickstart | Tablet-store-agent integration and persistence verification |
| Model Armor | Governance walkthrough and template discussion | Explicit service/template setup and runtime enforcement integration |
| Promotion pipeline | Checked-in build definitions and setup scripts | Verify the actual repository connection, triggers, approvals and environment engines |
| Five introductory deck slides | No insertion verified by this repository audit | Confirm the current deck, create/review the five slides and verify their insertion |

Keep release evidence tied to a commit and environment. Do not convert a passing offline check into a
claim about a deployed service. Attendee pages should teach the available implementation without a project backlog table.
