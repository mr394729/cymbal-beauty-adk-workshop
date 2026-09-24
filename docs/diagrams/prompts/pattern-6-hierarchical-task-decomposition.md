# pattern-6-hierarchical-task-decomposition

**Title:** Pattern 6 · Hierarchical task decomposition — the one-pager diagram (text on the left of the slide, this image on the right)

**Aspect:** 1:1

**Creative direction:** `_creative_direction.md` (Google Cloud palette, Cymbal Beauty branding, no logos)

**Pipeline:** gemini-diagramming. Step 1 `gemini-3.8-flash` (thinking HIGH) crafts the image prompt from the description below; Step 2 `gemini-3.1-flash-image` renders 1:1 at `image_size=4K` with thinking off. The numbered circles match the "Agentic flow" steps on the one-pager (see `docs/patterns/README.md`).

**Source of truth:** `agents/cymbal_store_ops/sub_agents/daily_briefing.py` (`make_daily_briefing_tool`), `agents/cymbal_store_ops/agent.py`

## Description (Step 1 input — edit this to regenerate)

The canvas is SQUARE (1:1), not 16:9: this image sits on the right half of a slide, beside the text. Fewer, larger elements; every label must stay legible when the square is shown at about 900 px.

Render this as a TOP-TO-BOTTOM zoom: a tool on the outside, a tree on the inside.

TITLE (top-left): "Hierarchical task decomposition"
SUBTITLE: "A multi-step task handed to a workflow that the coordinator calls as one tool"

TOP: a Blue box "store_manager_agent" and, to its right, a Yellow gear box "daily_briefing" with second line "AgentTool · one tool call". A Blue arrow from the root to the Yellow box, with circle 1 on it.

MIDDLE: below the Yellow box, a large rounded region with a thick Yellow border (the inside of the tool), connected to the Yellow box by two thin Yellow lines like a magnifier. Inside it:
  A light-blue region with a solid Blue border titled "SequentialAgent · daily_briefing", with circle 2 at its top-left.
  Inside that, left to right: a light-blue region with a DASHED Blue border titled "ParallelAgent · signals" holding three small Blue boxes stacked: "briefing_inventory", "briefing_coverage", "briefing_shrink" (circle 3 beside them); then a Blue arrow to one Blue box "plan_writer" with second line "structured briefing" (circle 4 beside it).

BOTTOM: a Blue arrow from the tool back up to the root labeled "one answer", with circle 5 on it.
Beside it, one Orange pill: "seeded from the caller's state · state changes flow back · temp: keys expire · action_plan persists".
Under the root, one small Gray note: "the root never sees the inside".

Exactly one root, one tool, one sequence, one parallel stage with three branches and one writer. No other components.

NUMBERED STEPS: small Charcoal circles with a white number ("1" to "5") sit on or beside the arrows they describe, exactly one circle per number, and nothing else is numbered.
NO FOOTER: there is no strip, bar, caption or footer line at the bottom of the canvas. The diagram uses the full height of the square, vertically centred under the title.
The only text on the canvas is the quoted labels above. Every box sits fully inside the canvas with a clear margin; nothing is cropped by the edge. Generous padding; arrows route around boxes; all labels horizontal. Every box is wide enough that its identifier stays on one line and never breaks at an underscore.
TEXT AND COLOR GUARD: the picture contains no text except the double-quoted strings in this description. Words written in capitals here (TITLE, SUBTITLE, TOP, MIDDLE, BOTTOM, LEFT, RIGHT, NUMBERED STEPS, NO FOOTER and the like) are layout instructions and never appear in the picture. In your prompt, name colors only by word (Blue, Yellow, Green, Red, Purple, Orange, Gray, Charcoal) and never write a hex code; describe positions in lowercase prose and never give a region, row, bar or legend a name of its own. A region with no quoted title has no title.
## Crafted image prompt (Step 1 output used for the current render)

A professional, high-resolution technical software architecture diagram in a square 1:1 aspect ratio, designed for workshop slides and documentation. Modern flat 2D vector graphic aesthetic, pure white background, generous margins, sharp geometric shapes, and clear hierarchy.

### Typography & Palette
- Typography: Clean, crisp geometric sans-serif for titles and prose, clean monospace for identifiers with underscores. All text must be horizontal, fully legible, and never broken across lines at underscores.
- Palette: Primary Blue, tool Yellow, configuration Orange, dark Charcoal for text/borders, Medium Gray for annotations/lines, Light Blue and Light Yellow for container fills. No gradients, no 3D effects, no drop shadows.

### Top Header
- Positioned in the upper-left corner:
  - Main Title (large, bold Charcoal): "Hierarchical task decomposition"
  - Subtitle directly underneath (medium, regular Medium Gray): "A multi-step task handed to a workflow that the coordinator calls as one tool"

### High-Level Top Section
- Positioned horizontally below the header:
  - On the left: A solid Blue rounded rectangle box with white bold monospace text reading "store_manager_agent". Directly beneath this box sits a small, regular Medium Gray annotation reading "the root never sees the inside".
  - To the right: A solid Yellow rounded rectangle box featuring a minimal generic gear icon glyph beside Charcoal text: top line bold monospace "daily_briefing", second line regular "AgentTool · one tool call".
  - A crisp Blue directional arrow points horizontally from "store_manager_agent" to "daily_briefing". Positioned directly on this arrow is a small, solid Charcoal circle containing the white number "1".

### Middle Magnified View (Inside the Tool)
- Beneath the top Yellow box, two thin, light Yellow projection lines extend downward like a magnifying callout to a large rounded rectangular container featuring a thick Yellow solid border and a very pale, light yellow fill.
- Inside this Yellow container:
  - A large inner container with a solid Blue border and light blue fill. Near its top-left corner is a small solid Charcoal circle containing the white number "2", placed immediately beside the bold Charcoal header label "SequentialAgent · daily_briefing".
  - Inside this sequential container, arranged horizontally from left to right:
    1. A sub-container with a dashed Blue border and pale blue fill, titled at its top in bold Charcoal monospace "ParallelAgent · signals". Inside it, stacked vertically with balanced spacing, are three distinct solid Blue rounded rectangular boxes with white monospace text:
       - "briefing_inventory"
       - "briefing_coverage"
       - "briefing_shrink"
       Beside this dashed group sits a small solid Charcoal circle with the white number "3".
    2. A Blue directional arrow routes horizontally from the dashed parallel group toward the right.
    3. On the right: A solid Blue rounded rectangular box with white text: top line bold monospace "plan_writer", second line regular "structured briefing". Beside this box sits a small solid Charcoal circle with the white number "4".

### Return Flow & State Banner
- A crisp Blue return arrow routes upward from the Yellow tool container back to the "store_manager_agent" box, labeled with Medium Gray text "one answer", with a small solid Charcoal circle containing the white number "5" sitting on the arrow.
- Near the bottom, centered horizontally with ample breathing room: A solid Orange rounded pill container with dark Charcoal text reading:
  "seeded from the caller's state · state changes flow back · temp: keys expire · action_plan persists"

### Formatting Constraints
- Exactly one root box, one tool box, one sequential container, one parallel group with three stacked boxes, and one writer box.
- Exactly five numbered circles ("1", "2", "3", "4", "5") in solid Charcoal with white numerals.
- No footer bar, status strip, or bottom border line. The diagram is vertically balanced across the square canvas with generous padding around all components.
