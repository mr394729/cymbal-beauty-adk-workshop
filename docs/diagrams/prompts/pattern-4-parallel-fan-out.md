# pattern-4-parallel-fan-out

**Title:** Pattern 4 · Parallel fan-out and gather — the one-pager diagram (text on the left of the slide, this image on the right)

**Aspect:** 1:1

**Creative direction:** `_creative_direction.md` (Google Cloud palette, Cymbal Beauty branding, no logos)

**Pipeline:** gemini-diagramming. Step 1 `gemini-3.8-flash` (thinking HIGH) crafts the image prompt from the description below; Step 2 `gemini-3.1-flash-image` renders 1:1 at `image_size=4K` with thinking off. The numbered circles match the "Agentic flow" steps on the one-pager (see `docs/patterns/README.md`).

**Source of truth:** `agents/cymbal_store_ops/sub_agents/daily_briefing.py`, `briefing_signals.py`, `briefing_facts.py`

## Description (Step 1 input — edit this to regenerate)

The canvas is SQUARE (1:1), not 16:9: this image sits on the right half of a slide, beside the text. Fewer, larger elements; every label must stay legible when the square is shown at about 900 px.

Render this as a LEFT-TO-RIGHT fan-out and gather.

TITLE (top-left): "Parallel fan-out and gather"
SUBTITLE: "Three independent reads run at once; one writer turns them into a plan"

LEFT: a Purple person box "Dana" with a wide white speech bubble whose text reads exactly, letter for letter: "What should I be on top of first?". An arrow to the right with circle 1 on it.

CENTER-LEFT: a light-blue region with a DASHED Blue border titled "ParallelAgent · signals". Arrows fan out from its left edge into three lanes, with circle 2 on the fan-out. Each lane is one Blue box with a Yellow tools line under it:
  "briefing_inventory" — tools "OSA exceptions · pickup demand · open tasks · merchandising work"
  "briefing_coverage" — tools "traffic · roster · guest feedback · coverage rules · pickup workload"
  "briefing_shrink" — tools "shrink signals · task history · loss controls"
  Each lane box carries a small Gray badge "reads in code · no model call".
  From the right end of each lane, an Orange state chip: "temp:briefing_inventory", "temp:briefing_coverage", "temp:briefing_shrink", with circle 3 beside the middle chip.

CENTER-RIGHT: the three chips converge with arrows into one Blue box "plan_writer" with second line "one Gemini call · selected source facts", with circle 4 on the converging arrows.

RIGHT: an Orange state box "action_plan" with three numbered lines "1 inventory", "2 coverage", "3 loss", and under it a white chat card "the briefing · 3–5 suggested next steps". Circle 5 on the arrow from "plan_writer".

A small Gray note under the region: "the stage takes as long as its slowest branch".

Exactly one person, one parallel region with three lanes, three state chips, one writer, one plan box and one chat card. No other components.

NUMBERED STEPS: small Charcoal circles with a white number ("1" to "5") sit on or beside the arrows they describe, exactly one circle per number, and nothing else is numbered.
NO FOOTER: there is no strip, bar, caption or footer line at the bottom of the canvas. The diagram uses the full height of the square, vertically centred under the title.
The only text on the canvas is the quoted labels above. Every box sits fully inside the canvas with a clear margin; nothing is cropped by the edge. Generous padding; arrows route around boxes; all labels horizontal. Every box is wide enough that its identifier stays on one line and never breaks at an underscore.
TEXT AND COLOR GUARD: the picture contains no text except the double-quoted strings in this description. Words written in capitals here (TITLE, SUBTITLE, TOP, MIDDLE, BOTTOM, LEFT, RIGHT, NUMBERED STEPS, NO FOOTER and the like) are layout instructions and never appear in the picture. In your prompt, name colors only by word (Blue, Yellow, Green, Red, Purple, Orange, Gray, Charcoal) and never write a hex code; describe positions in lowercase prose and never give a region, row, bar or legend a name of its own. A region with no quoted title has no title.
## Crafted image prompt (Step 1 output used for the current render)

A clean, professional technical software architecture diagram on a pure solid White square background (1:1 aspect ratio), designed in a modern flat vector documentation style with crisp lines, generous padding, and clear visual hierarchy.

At the top left:
Diagram title in large, bold Charcoal sans-serif text: "Parallel fan-out and gather"
Immediately beneath the title, subtitle in regular Medium Gray sans-serif text: "Three independent reads run at once; one writer turns them into a plan"

The diagram flows cleanly from left to right across the canvas:

1. Left section:
A solid Purple rounded rectangle box labeled "Dana" in bold White text, featuring a simple white person silhouette glyph. Attached to it is a wide White speech bubble card with a subtle Charcoal outline, containing the text in Charcoal: "What should I be on top of first?".
A directional gray horizontal arrow points to the right toward the central region. On this arrow sits a small solid Charcoal circular badge with the numeral "1" in bold White.

2. Center-left region:
A large Light-blue tinted container with a dashed Blue border and rounded corners. Along its top interior edge, a label in bold Blue sans-serif reads: "ParallelAgent · signals".
The incoming arrow from step 1 enters the container and fans out into three horizontal lanes. On the fan-out junction sits a small solid Charcoal circular badge with the numeral "2" in bold White.
Inside the container, arranged vertically as three distinct parallel lanes:

- Top lane:
A solid Blue rounded rectangle box with bold White text: "briefing_inventory". Inside the top-right corner or attached to it is a small Light Gray pill badge with Charcoal text: "reads in code · no model call". Directly below the blue box is a Yellow horizontal pill containing Charcoal text: "OSA exceptions · pickup demand · open tasks · merchandising work".
Extending to the right from this lane is an Orange rounded chip with bold Charcoal text: "temp:briefing_inventory".

- Middle lane:
A solid Blue rounded rectangle box with bold White text: "briefing_coverage". Attached is a small Light Gray pill badge with Charcoal text: "reads in code · no model call". Directly below the blue box is a Yellow horizontal pill containing Charcoal text: "traffic · roster · guest feedback · coverage rules · pickup workload".
Extending to the right from this lane is an Orange rounded chip with bold Charcoal text: "temp:briefing_coverage". Beside this middle chip sits a small solid Charcoal circular badge with the numeral "3" in bold White.

- Bottom lane:
A solid Blue rounded rectangle box with bold White text: "briefing_shrink". Attached is a small Light Gray pill badge with Charcoal text: "reads in code · no model call". Directly below the blue box is a Yellow horizontal pill containing Charcoal text: "shrink signals · task history · loss controls".
Extending to the right from this lane is an Orange rounded chip with bold Charcoal text: "temp:briefing_shrink".

Directly beneath this Light-blue container, centered horizontally, is an annotation in italic Medium Gray sans-serif text: "the stage takes as long as its slowest branch".

3. Center-right section:
Gray connection arrows extend from the right ends of all three Orange state chips and converge together toward the right. On this converging arrow intersection sits a small solid Charcoal circular badge with the numeral "4" in bold White.
The converging arrows point directly into a prominent Blue rounded rectangle box. Inside this box, line one in bold White text reads: "plan_writer", and line two in regular White text reads: "one Gemini call · selected source facts".

4. Right section:
A horizontal gray arrow leads from the "plan_writer" box to the rightmost stack. On this arrow sits a small solid Charcoal circular badge with the numeral "5" in bold White.
The arrow connects to a vertical card structure:
- Upper element: An Orange rounded rectangle box titled "action_plan" in bold Charcoal text, containing three neat left-aligned bulleted lines in Charcoal text:
  "1 inventory"
  "2 coverage"
  "3 loss"
- Lower element: Positioned directly beneath the orange box, a clean White chat card with a subtle Charcoal border displaying horizontal Charcoal text: "the briefing · 3–5 suggested next steps".

Design and styling specifications:
- Pure white background with no gradients, no photorealism, no 3D bevels, and no drop shadow effects.
- Strict color palette: Blue, Yellow, Orange, Purple, Gray, Charcoal, Light-blue, and White.
- All boxes have rounded corners with consistent 12px corner radii.
- All text strings must be perfectly horizontal, fully visible, clearly legible, and spelled exactly as double-quoted.
- All component boxes are sufficiently wide to prevent text wrapping on single-line identifiers.
- Generous margins and breathing room on all sides with no overlapping elements, perfectly centered vertically in the square canvas. No footer or bottom metadata bar.
