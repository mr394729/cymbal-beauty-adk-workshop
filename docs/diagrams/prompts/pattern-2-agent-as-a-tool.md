# pattern-2-agent-as-a-tool

**Title:** Pattern 2 · Agent as a tool (single_turn) — the one-pager diagram (text on the left of the slide, this image on the right)

**Aspect:** 1:1

**Creative direction:** `_creative_direction.md` (Google Cloud palette, Cymbal Beauty branding, no logos)

**Pipeline:** gemini-diagramming. Step 1 `gemini-3.8-flash` (thinking HIGH) crafts the image prompt from the description below; Step 2 `gemini-3.1-flash-image` renders 1:1 at `image_size=4K` with thinking off. The numbered circles match the "Agentic flow" steps on the one-pager (see `docs/patterns/README.md`).

**Source of truth:** `agents/cymbal_store_ops/sub_agents/inventory_excellence.py`, `associate_orchestration.py`, `loss_prevention.py`, `mcp_catalog.py`, `services/store_mcp/server.py`

## Description (Step 1 input — edit this to regenerate)

The canvas is SQUARE (1:1), not 16:9: this image sits on the right half of a slide, beside the text. Fewer, larger elements; every label must stay legible when the square is shown at about 900 px.

Render this as a LEFT-TO-RIGHT round trip.

TITLE (top-left): "Agent as a tool"
SUBTITLE: "A specialist answers one typed question and hands control straight back"

LEFT: a Purple person box "Dana · store manager" with a white speech bubble "Why is Hydra Cream flagged?".
  A Blue box "store_manager_agent" with second line "keeps the conversation" to the right of Dana, joined by a Purple arrow.
  Circle 1 beside the root with a small Blue note "needs stock facts".

CENTER: a Blue box with a thick border "inventory_excellence" with three short lines inside: "mode: single_turn", "input: OsaQuery", "no conversation history".
  A straight Blue arrow from "store_manager_agent" to "inventory_excellence", labeled "typed query", with circle 2 on that arrow.

RIGHT: the main row continues at the same height, left to right after "inventory_excellence": one Blue box "MCP server" with three smaller lines inside it, "get_osa_exceptions · check_store_stock", "find_nearby_stock · get_bopis_demand" and "store and role checked"; then, at the far right, a Green database cylinder "BigQuery · store data". A straight Blue arrow from "inventory_excellence" into "MCP server", with circle 3 on it, and a straight Green arrow from "MCP server" into the cylinder.

RETURN: a Blue arrow from "inventory_excellence" back to the root labeled "one answer", with circle 4 on it. On that arrow, one Orange state chip "last_osa".
  A Purple arrow from the root back to Dana labeled "the reply", with circle 5 on it.

BELOW the center, two small Gray boxes side by side, dimmed: "associate_orchestration → last_coverage" and "loss_prevention → last_shrink", with a shared Gray caption "the same pattern".

Exactly one person, one root, one specialist, one MCP server box, one cylinder and two dimmed boxes. There is no separate tools box. No other components.

NUMBERED STEPS: small Charcoal circles with a white number ("1" to "5") sit on or beside the arrows they describe, exactly one circle per number, and nothing else is numbered.
NO FOOTER: there is no strip, bar, caption or footer line at the bottom of the canvas. The diagram uses the full height of the square, vertically centred under the title.
The only text on the canvas is the quoted labels above. Every box sits fully inside the canvas with a clear margin; nothing is cropped by the edge. Generous padding; arrows route around boxes; all labels horizontal. Every box is wide enough that its identifier stays on one line and never breaks at an underscore.
NO HEADINGS GUARD: apart from the title and subtitle, no box has any heading, category or type label above, beside or inside it beyond its own quoted text. Never describe a component in the prompt by a made-up role name; refer to each only by its quoted text.
TEXT AND COLOR GUARD: the picture contains no text except the double-quoted strings in this description. Words written in capitals here (TITLE, SUBTITLE, TOP, MIDDLE, BOTTOM, LEFT, RIGHT, NUMBERED STEPS, NO FOOTER and the like) are layout instructions and never appear in the picture. In your prompt, name colors only by word (Blue, Yellow, Green, Red, Purple, Orange, Gray, Charcoal) and never write a hex code; describe positions in lowercase prose and never give a region, row, bar or legend a name of its own. A region with no quoted title has no title.
## Crafted image prompt (Step 1 output used for the current render)

A clean, professional technical architecture diagram on a square 1:1 aspect ratio canvas with a solid White background. Flat 2D vector aesthetic, crisp lines, modern sans-serif typography, generous white space, and balanced spacing suited for presentation slides.

TOP LEFT HEADER:
- Primary diagram title in large, bold Charcoal text: "Agent as a tool"
- Subtitle directly beneath in regular Charcoal text: "A specialist answers one typed question and hands control straight back"

MAIN HORIZONTAL ROW (aligned horizontally across the middle of the canvas from left to right):
1. Far Left: A solid Purple rounded rectangle box labeled with bold white text "Dana · store manager". Attached above it is a clean white speech bubble with a thin Purple outline containing Charcoal text: "Why is Hydra Cream flagged?".
2. Second component: A solid Blue rounded rectangle labeled with bold white text "store_manager_agent" on the top line, and smaller white text "keeps the conversation" on the line below.
   - A forward Purple arrow connects "Dana · store manager" to "store_manager_agent".
   - Beside "store_manager_agent" sits a small solid Charcoal circle containing white number "1", next to a small Blue text annotation: "needs stock facts".
3. Center component: A large rounded rectangle with a thick, distinct solid Blue border and very light blue tinted background, containing bold Blue title text "inventory_excellence", followed by three separate horizontal lines of Charcoal text:
   - Line 1: "mode: single_turn"
   - Line 2: "input: OsaQuery"
   - Line 3: "no conversation history"
   - A straight horizontal Blue arrow connects "store_manager_agent" to "inventory_excellence", labeled above with regular Charcoal text "typed query". A small solid Charcoal circle containing white number "2" sits directly on this arrow.
4. Fourth component: A solid Blue rounded rectangle labeled with bold white text "MCP server", containing three smaller horizontal lines of text inside:
   - Line 1: "get_osa_exceptions · check_store_stock"
   - Line 2: "find_nearby_stock · get_bopis_demand"
   - Line 3: "store and role checked"
   - A straight horizontal Blue arrow connects "inventory_excellence" to "MCP server", with a small solid Charcoal circle containing white number "3" positioned on the arrow.
5. Far Right component: A solid Green vertical database cylinder labeled with bold white text: "BigQuery · store data".
   - A straight horizontal Green arrow connects "MCP server" into "BigQuery · store data".

RETURN PATHS (routed neatly below the forward arrows):
- A smooth Blue return arrow routes backward from "inventory_excellence" to "store_manager_agent". It is labeled with Charcoal text "one answer" and features a small solid Charcoal circle containing white number "4". Placed directly alongside this return arrow is a small solid Orange rounded chip containing Charcoal text: "last_osa".
- A smooth Purple return arrow routes backward from "store_manager_agent" to "Dana · store manager", labeled with Charcoal text "the reply", featuring a small solid Charcoal circle containing white number "5".

LOWER SECTION (centered underneath the main components):
- Two small, dimmed light Gray rounded rectangles positioned horizontally side by side with thin Gray outlines:
  - Left box containing Charcoal text: "associate_orchestration → last_coverage"
  - Right box containing Charcoal text: "loss_prevention → last_shrink"
- Centered relative to these two dimmed boxes is a small medium Gray text label: "the same pattern".

STRICT VISUAL RULES:
- The canvas contains exactly five numbered Charcoal circles ("1", "2", "3", "4", "5") and no others.
- Exactly one person box, one root agent box, one center specialist box, one MCP server box, one cylinder database, and two dimmed gray boxes.
- All text strings appear strictly horizontal, correctly spelled, and enclosed in double quotes. No other text, category labels, footers, or decorative borders exist on the canvas. Generous outer margins around the entire composition.
