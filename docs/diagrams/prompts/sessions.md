# sessions

**Slide:** none (repository diagram: docs/ARCHITECTURE.md, frontend/ARCHITECTURE.md)

**Aspect:** 16:9

**Pipeline:** gemini-diagramming. Step 1 `gemini-3.8-flash` (thinking HIGH) crafts the image prompt from the description below; Step 2 `gemini-3.1-flash-image` renders 16:9 at `image_size=4K` with thinking off. Creative direction: `_creative_direction.md`. The page supplies the title and the copy, so the image carries no title.

**Source of truth:** `frontend/server.py` (DEMO_IDENTITIES, owned_session), `frontend/session_access.py`, `agents/cymbal_store_ops/context_history.py`, `quickstarts/` memory example

## Description (Step 1 input — edit this to regenerate)

The canvas is 16:9. This image sits under a heading on a documentation page, so the image has NO title, NO subtitle and NO footer. Fewer, larger elements; every label must stay legible when the image is shown about 900 px wide.

TWO TEXT LEVELS: a box has a bold name and, where given, one or two smaller regular lines under it.

Render this as THREE COLUMNS left to right. The left and middle columns are joined by one thick right-pointing arrow. The right column is separated from the middle by a vertical dashed Gray line and is NOT joined by any arrow.

LEFT COLUMN, one tall rounded box with a light purple fill and a Purple border and a person glyph at its top left. Bold name "Who is signed in", smaller lines: "user, role and store set by the app at sign-in", "never taken from the chat", "a different role is a different user". Inside the box at the bottom, three small White chips with a Purple border in a row: "user:role", "user:store_id", "user:user_id".

MIDDLE COLUMN, one tall rounded box with a light blue fill and a Blue border. Bold name "One conversation", smaller lines: "every message, tool call and result is an event", "state carries the plan and follow-up context", "finished specialist transcripts are pruned before the next model call". Inside the box at the bottom, two small White chips with a Blue border in a row: "session events", "session state".

Between the left and middle boxes one thick Charcoal arrow pointing right with the small label "seeds the session".

RIGHT COLUMN, one shorter rounded box with a light gray fill and a dashed Gray border. Bold name "Long-term memory", smaller lines: "a separate service, searched on demand", "shown in a standalone quickstart", "not part of the store agent's conversation". Inside the box at the bottom, one small White chip with a Gray border: "Memory Bank".

BOTTOM, one thin Red strip under the left and middle columns only: "every session route checks the signed-in owner and role; someone else's conversation is not found".

Exactly three boxes, six chips, one arrow, one dashed divider and one strip. No other components.

The only text on the canvas is the quoted labels above. Every box sits fully inside the canvas with a clear margin; nothing is cropped by the edge. Generous padding; arrows route around boxes; all labels horizontal. Every box is wide enough that its label stays on one line and an identifier never breaks at an underscore.
TEXT AND COLOR GUARD: the picture contains no text except the double-quoted strings in this description, and no retailer or vendor name or logo. Words written in capitals here (TOP, MIDDLE, BOTTOM, LEFT, RIGHT, CENTER, ROW, COLUMN, LANE and the like) are layout instructions and never appear in the picture. In your prompt, name colors only by word (Blue, Yellow, Green, Red, Purple, Orange, Gray, Charcoal) and never write a hex code; describe positions in lowercase prose and never give a region, row, bar or legend a name of its own. A region with no quoted title has no title.
## Crafted image prompt (Step 1 output used for the current render)

A clean, high-resolution 16:9 technical architecture diagram on a solid white background, designed with a flat vector aesthetic, crisp lines, generous padding, and clear typographic hierarchy. The canvas contains no overall diagram title, no subtitle, and no footer.

The diagram is organized horizontally into three distinct columns:

On the left, a tall rounded rectangle box with a light purple fill and a solid Purple border. In the upper-left corner inside the box is a small, minimalist flat vector glyph of a person silhouette in Purple. At the top of the box is the bold title "Who is signed in" in Charcoal sans-serif text. Directly underneath are three separate horizontal lines of smaller, regular Charcoal text:
"user, role and store set by the app at sign-in"
"never taken from the chat"
"a different role is a different user"
At the bottom inside this box is a horizontal row containing exactly three rounded White chips with solid Purple borders, each containing Charcoal text:
The first chip reads "user:role"
The second chip reads "user:store_id"
The third chip reads "user:user_id"

In the middle, a tall rounded rectangle box of identical height to the left box, with a light blue fill and a solid Blue border. At the top of the box is the bold title "One conversation" in Charcoal sans-serif text. Directly underneath are three separate horizontal lines of smaller, regular Charcoal text:
"every message, tool call and result is an event"
"state carries the plan and follow-up context"
"finished specialist transcripts are pruned before the next model call"
At the bottom inside this box is a horizontal row containing exactly two rounded White chips with solid Blue borders, each containing Charcoal text:
The first chip reads "session events"
The second chip reads "session state"

Connecting the left box to the middle box is a single thick horizontal Charcoal arrow pointing directly from the right edge of the left box to the left edge of the middle box. Centered along this arrow is a horizontal Charcoal label:
"seeds the session"

Between the middle column and the right column is a single vertical dashed Gray line running top to bottom as a visual boundary. No arrows cross or touch this line.

On the right, separated by the vertical dashed Gray line, is a shorter rounded rectangle box with a light gray fill and a dashed Gray border. At the top of the box is the bold title "Long-term memory" in Charcoal sans-serif text. Directly underneath are three separate horizontal lines of smaller, regular Charcoal text:
"a separate service, searched on demand"
"shown in a standalone quickstart"
"not part of the store agent's conversation"
At the bottom inside this box is a single rounded White chip with a solid Gray border containing Charcoal text:
"Memory Bank"

Directly beneath the left and middle boxes only, spanning their combined horizontal width and terminating before the dashed Gray line, is a single thin horizontal strip with a light red fill and a solid Red border. Centered horizontally inside this strip is Charcoal text:
"every session route checks the signed-in owner and role; someone else's conversation is not found"

The composition contains strictly three boxes, six chips, one connecting arrow, one dashed vertical divider line, and one bottom strip. All text is perfectly horizontal, clearly legible, and strictly limited to the quoted strings provided. No gradients, no drop shadows, no 3D effects, and no company logos.
