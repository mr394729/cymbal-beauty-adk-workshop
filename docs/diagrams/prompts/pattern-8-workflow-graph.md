# pattern-8-workflow-graph

**Title:** Pattern 8 · Workflow graph (ADK 2.x) — the one-pager diagram (text on the left of the slide, this image on the right)

**Aspect:** 1:1

**Creative direction:** `_creative_direction.md` (Google Cloud palette, Cymbal Beauty branding, no logos)

**Pipeline:** gemini-diagramming. Step 1 `gemini-3.8-flash` (thinking HIGH) crafts the image prompt from the description below; Step 2 `gemini-3.1-flash-image` renders 1:1 at `image_size=4K` with thinking off. The numbered circles match the "Agentic flow" steps on the one-pager (see `docs/patterns/README.md`).

**Source of truth:** `quickstarts/10-multi-agent-router/patterns/05_workflow_graph.py`

## Description (Step 1 input — edit this to regenerate)

The canvas is SQUARE (1:1), not 16:9: this image sits on the right half of a slide, beside the text. Fewer, larger elements; every label must stay legible when the square is shown at about 900 px.

Render this as a LEFT-TO-RIGHT graph: one entry, three routes, one exit.

TITLE (top-left): "Workflow graph"
SUBTITLE: "Code chooses the route; the model reasons inside each node"

LEFT: a Gray box "store exception event" with second line "Pub/Sub or Eventarc in production" and a small white JSON card "{ type: osa, product_id: P-0101 }". An arrow into the graph with circle 1 on it.

A large light-blue region with a solid Blue border titled "Workflow · exception_router". Inside it, left to right:
  A small Gray "START" dot.
  A Gray code box "classify_event" with second line "@node · reads the type field". Circle 2 beside it. Attached to it, one Orange pill "retry_config · 2 attempts on TimeoutError", with circle 3 beside the pill.
  Three arrows fan out from "classify_event", each labeled with its route: "osa", "coverage", "shrink", into three Blue boxes stacked vertically:
    "osa_handler" with Yellow tools line "check_store_stock · get_bopis_demand"
    "coverage_handler" with Yellow tools line "get_traffic_and_backlog · get_shift_roster"
    "shrink_handler" with Yellow tools line "get_shrink_signals"
  Circle 4 beside the three handlers.
  The three handlers converge on one Gray code box "notify_manager" with second line "plain function · reads resolution from state", with circle 5 on the converging arrows.

Below "classify_event", a Red arrow down to a Red box "unknown type → ValueError · refused".

Exactly one event, one classifier, three handlers, one notify node and one Red refusal. No other components.

NUMBERED STEPS: small Charcoal circles with a white number ("1" to "5") sit on or beside the arrows they describe, exactly one circle per number, and nothing else is numbered.
NO FOOTER: there is no strip, bar, caption or footer line at the bottom of the canvas. The diagram uses the full height of the square, vertically centred under the title.
The only text on the canvas is the quoted labels above. Every box sits fully inside the canvas with a clear margin; nothing is cropped by the edge. Generous padding; arrows route around boxes; all labels horizontal. Every box is wide enough that its identifier stays on one line and never breaks at an underscore.
TEXT AND COLOR GUARD: the picture contains no text except the double-quoted strings in this description. Words written in capitals here (TITLE, SUBTITLE, TOP, MIDDLE, BOTTOM, LEFT, RIGHT, NUMBERED STEPS, NO FOOTER and the like) are layout instructions and never appear in the picture. In your prompt, name colors only by word (Blue, Yellow, Green, Red, Purple, Orange, Gray, Charcoal) and never write a hex code; describe positions in lowercase prose and never give a region, row, bar or legend a name of its own. A region with no quoted title has no title.
## Crafted image prompt (Step 1 output used for the current render)

A square (1:1 aspect ratio) technical software architecture diagram on a clean solid White background, optimized for presentation slides at 4K resolution. The diagram uses a crisp, modern flat design with bold legible typography, generous white space, rounded rectangle nodes, clean directional arrows, and high contrast.

At the top left of the canvas:
- Main title in large bold Charcoal text: "Workflow graph"
- Subtitle directly underneath in regular Medium Gray text: "Code chooses the route; the model reasons inside each node"

On the left side, vertically centered:
- A Gray rounded rectangle box with a Charcoal border containing the bold Charcoal text "store exception event", with a second line beneath it in smaller Charcoal text reading "Pub/Sub or Eventarc in production". Inside this box at the bottom is a small White card with a subtle Charcoal border displaying monospace text: "{ type: osa, product_id: P-0101 }".
- A clean horizontal directional arrow extends from this box to the right, entering the main workflow container. Centered on this arrow is a small Charcoal solid circular badge displaying a crisp white number "1".

In the center and right area of the canvas:
- A large Light Blue container with rounded corners and a solid Blue border. Near the top-left inside corner of this container is the header text in bold Blue: "Workflow · exception_router".
- Inside the container, arranged from left to right:
  1. A small solid Gray circle labeled with horizontal Charcoal text "START".
  2. A directional arrow leads from "START" to a Gray rounded rectangle code box labeled with bold Charcoal text "classify_event", and a second line beneath reading "@node · reads the type field".
     - Directly beside this box is a small Charcoal solid circular badge with a white number "2".
     - Attached to the top edge of this box is an Orange pill badge containing Charcoal text: "retry_config · 2 attempts on TimeoutError". Beside this pill sits a small Charcoal solid circular badge with a white number "3".
  3. Directly below the "classify_event" box, a solid Red arrow points straight down to a Red outlined box with a soft Light Red fill, containing bold Red text: "unknown type → ValueError · refused".
  4. From the right edge of "classify_event", three clean directional arrows fan out toward the right, each with a neat horizontal label:
     - The top arrow is labeled "osa"
     - The middle arrow is labeled "coverage"
     - The bottom arrow is labeled "shrink"
  5. The three arrows connect respectively into three vertically stacked Blue rounded rectangle boxes:
     - Top box: bold white text "osa_handler", with a horizontal Yellow pill label underneath inside the box reading Charcoal text "check_store_stock · get_bopis_demand".
     - Middle box: bold white text "coverage_handler", with a horizontal Yellow pill label underneath inside the box reading Charcoal text "get_traffic_and_backlog · get_shift_roster".
     - Bottom box: bold white text "shrink_handler", with a horizontal Yellow pill label underneath inside the box reading Charcoal text "get_shrink_signals".
     - Positioned immediately to the right of these three handler boxes is a small Charcoal solid circular badge with a white number "4".
  6. Three directional arrows emerge from the right edge of each handler box and converge toward the right into a single Gray code box. Centered along these converging paths is a small Charcoal solid circular badge with a white number "5".
  7. The converging arrows terminate at a Gray rounded rectangle box containing bold Charcoal text "notify_manager", with a second line beneath reading Charcoal text "plain function · reads resolution from state".

Layout and styling rules:
- Perfectly square composition with ample empty space around all perimeter borders.
- No footers, captions, status bars, legends, or baseline strips at the bottom.
- Exactly five numbered Charcoal badges ("1", "2", "3", "4", "5") across the entire diagram.
- All text strings appear exactly as quoted, perfectly horizontal, fully legible, and never hyphenated or split across underscores.
- Flat 2D vector aesthetic with crisp lines, uniform stroke widths, and no 3D effects, gradients, or extraneous decorations.
