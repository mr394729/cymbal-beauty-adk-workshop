# pattern-3-sequential-pipeline

**Title:** Pattern 3 · Sequential pipeline — the one-pager diagram (text on the left of the slide, this image on the right)

**Aspect:** 1:1

**Creative direction:** `_creative_direction.md` (Google Cloud palette, Cymbal Beauty branding, no logos)

**Pipeline:** gemini-diagramming. Step 1 `gemini-3.8-flash` (thinking HIGH) crafts the image prompt from the description below; Step 2 `gemini-3.1-flash-image` renders 1:1 at `image_size=4K` with thinking off. The numbered circles match the "Agentic flow" steps on the one-pager (see `docs/patterns/README.md`).

**Source of truth:** `quickstarts/10-multi-agent-router/patterns/02_sequential_osa_to_task.py`

## Description (Step 1 input — edit this to regenerate)

The canvas is SQUARE (1:1), not 16:9: this image sits on the right half of a slide, beside the text. Fewer, larger elements; every label must stay legible when the square is shown at about 900 px.

Render this as a LEFT-TO-RIGHT pipeline inside one region.

TITLE (top-left): "Sequential pipeline"
SUBTITLE: "A fixed order: each stage's output_key is the next stage's input"

A large light-blue region with a solid Blue border titled "SequentialAgent · osa_to_task".
Inside it, left to right:
  A Blue box "osa_triage" with second line "writes output_key osa_finding". Under it, one Yellow gear box "get_osa_exceptions · get_bopis_demand". Circle 1 beside "osa_triage".
  One Orange state box "osa_finding" with second line "P-0101 · 0 on shelf · 7 backroom · 3 pickup orders", to the right of "osa_triage" and on the same horizontal line.
  The four main elements sit in ONE horizontal row: "osa_triage", then "osa_finding", then "task_drafter", then the draft card. There are EXACTLY THREE arrows in that row and no other horizontal arrows anywhere: from "osa_triage" to "osa_finding" labeled "SequentialAgent moves on" with circle 2 on it; from "osa_finding" to "task_drafter" labeled "{osa_finding} in the instruction" with circle 3 on it; from "task_drafter" to the draft card with circle 4 on it.
  A Blue box "task_drafter" with second line "include_contents: none". Under it, one Yellow gear box "get_task_status".
  A white card with a Charcoal border titled "Draft task" with three short lines: "backroom_check", "P-0101", "note with the counts".

Below the region, to the right, a Blue note with circle 5: "the last output is the answer".
Below that, one Red padlock chip: "a draft only · the write is store_tasks, behind a confirmation".

Exactly two agents, two tools boxes, one state box and one draft card. No other components.

NUMBERED STEPS: small Charcoal circles with a white number ("1" to "5") sit on or beside the arrows they describe, exactly one circle per number, and nothing else is numbered.
NO FOOTER: there is no strip, bar, caption or footer line at the bottom of the canvas. The diagram uses the full height of the square, vertically centred under the title.
The only text on the canvas is the quoted labels above. Every box sits fully inside the canvas with a clear margin; nothing is cropped by the edge. Generous padding; arrows route around boxes; all labels horizontal. Every box is wide enough that its identifier stays on one line and never breaks at an underscore.
TEXT AND COLOR GUARD: the picture contains no text except the double-quoted strings in this description. Words written in capitals here (TITLE, SUBTITLE, TOP, MIDDLE, BOTTOM, LEFT, RIGHT, NUMBERED STEPS, NO FOOTER and the like) are layout instructions and never appear in the picture. In your prompt, name colors only by word (Blue, Yellow, Green, Red, Purple, Orange, Gray, Charcoal) and never write a hex code; describe positions in lowercase prose and never give a region, row, bar or legend a name of its own. A region with no quoted title has no title.
## Crafted image prompt (Step 1 output used for the current render)

A clean, professional technical software architecture diagram on a solid white square 1:1 canvas, formatted for slide presentations with generous margins, crisp spacing, and high-contrast vector styling.

At the top left of the canvas:
- Main diagram title in bold, large Charcoal text: "Sequential pipeline"
- Directly underneath, subtitle in medium-weight Gray text: "A fixed order: each stage's output_key is the next stage's input"

In the center of the square canvas, spanning horizontally:
A large rectangular container with rounded corners, a light-blue tinted background, and a crisp solid Blue border. At the top left inside this container, the title reads in bold Blue text: "SequentialAgent · osa_to_task".

Inside this container, exactly four main components are arranged in a single horizontal row from left to right, evenly spaced with generous padding:

1. First component (far left):
   - A primary Blue rectangular box with rounded corners and white text. First line in bold: "osa_triage". Second line in regular text: "writes output_key osa_finding".
   - Beside the box, a small solid Charcoal circular badge containing the white number "1".
   - Directly underneath this Blue box, a connected Yellow rounded rectangular tool box featuring a small generic gear glyph and Charcoal text: "get_osa_exceptions · get_bopis_demand".

2. First connection:
   - A single horizontal gray arrow points from "osa_triage" to the state box to its right.
   - Above the arrow, horizontal regular Gray text reads: "SequentialAgent moves on".
   - On the arrow line, a small solid Charcoal circular badge containing the white number "2".

3. Second component:
   - An Orange rectangular state box with rounded corners and Charcoal text. First line in bold: "osa_finding". Second line in regular text: "P-0101 · 0 on shelf · 7 backroom · 3 pickup orders".

4. Second connection:
   - A single horizontal gray arrow points from "osa_finding" to the next agent box to its right.
   - Above the arrow, horizontal regular Gray text reads: "{osa_finding} in the instruction".
   - On the arrow line, a small solid Charcoal circular badge containing the white number "3".

5. Third component:
   - A primary Blue rectangular box with rounded corners and white text. First line in bold: "task_drafter". Second line in regular text: "include_contents: none".
   - Directly underneath this Blue box, a connected Yellow rounded rectangular tool box featuring a small generic gear glyph and Charcoal text: "get_task_status".

6. Third connection:
   - A single horizontal gray arrow points from "task_drafter" to the draft card to its right.
   - On the arrow line, a small solid Charcoal circular badge containing the white number "4".

7. Fourth component (far right):
   - A white card with rounded corners, a solid Charcoal border, and a subtle flat drop shadow.
   - Card header in bold Charcoal text: "Draft task".
   - Below the header, three horizontal lines of regular Charcoal text:
     "backroom_check"
     "P-0101"
     "note with the counts"

Below the main light-blue container, aligned to the bottom right:
- A horizontal callout row featuring a small solid Charcoal circular badge with the white number "5" next to Blue text: "the last output is the answer".
- Directly beneath that, a rounded Red chip with a solid Red fill, white text, and a simple generic outline of a padlock glyph: "a draft only · the write is store_tasks, behind a confirmation".

Visual style guidelines:
- Flat 2D vector graphic design, clean modern geometric sans-serif typography.
- All text must be rendered strictly horizontal, fully visible, unclipped, and large enough to remain legible at lower resolutions.
- Boxes must be wide enough that component names remain on a single line without wrapping.
- There are strictly three horizontal arrows in the main row and no other horizontal connectors anywhere.
- Absolutely no 3D elements, glossy textures, gradients, or realistic photographic rendering.
- No bottom footer bar, captions, or branding marks.
