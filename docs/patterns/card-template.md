# Pattern card template

Use the same structure for each notebook explanation, speaker card and single-slide brief. Choose one operational need and one pattern per card. Lead with the work the person can accomplish. Keep code identifiers in the technical reference area, not the main slide headline.

| Field | Content |
|---|---|
| User need | One concrete question or outcome for a store manager or associate. |
| Pattern | The implemented ADK mechanism, or the mechanism proposed for pending work. |
| What the agent does | One sentence describing the actual result, without implying an unimplemented integration. |
| How | Three to five stages. Distinguish model decisions, deterministic processing, data reads and approval steps. |
| Tool paths | Exact source files and relevant tools. Link the notebook that demonstrates the pattern. |
| Benefit | The practical effect for the person or the developer. |
| Trade-off | One meaningful cost, limitation or dependency. |
| Live proof | A specific question, expected observable behavior and trace/data/artifact evidence. State the verification status separately. |
| Architecture visual prompt | A brief for a diagram showing only these stages and the supported connections. |

For the slide, retain the title, user need, three-to-five-stage flow and one benefit. Use the rest as presenter notes. Do not add prototype labels, author attribution or validation badges to the visual. Keep implementation status in the preparation notes.

Visual direction: 16:9, Cymbal Beauty warm ivory and charcoal, restrained Google Cloud blue/green accents, amber for human review. Short horizontal labels and generous spacing. Show model calls, code and storage as different elements. A proposed event flow must not look like an already deployed integration. Existing rendered images are not evidence that a revised prompt has been rendered.

Before presenting a card, record the tested source revision, target, date and evidence location. “Code exists”, “local test passed” and “live deployment verified” are different claims. Pending patterns remain design discussions until their acceptance checks pass.
