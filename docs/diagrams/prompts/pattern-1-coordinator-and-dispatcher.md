# pattern-1-coordinator-and-dispatcher

**Title:** Pattern 1 · Coordinator and dispatcher — the one-pager diagram (text on the left of the slide, this image on the right)

**Aspect:** 1:1

**Creative direction:** `_creative_direction.md` (Google Cloud palette, Cymbal Beauty branding, no logos)

**Pipeline:** gemini-diagramming. Step 1 `gemini-3.8-flash` (thinking HIGH) crafts the image prompt from the description below; Step 2 `gemini-3.1-flash-image` renders 1:1 at `image_size=4K` with thinking off. The numbered circles match the "Agentic flow" steps on the one-pager (see `docs/patterns/README.md`).

**Source of truth:** `agents/cymbal_store_ops/agent.py`, `sub_agents/associate_development.py`

## Description (Step 1 input — edit this to regenerate)

The canvas is SQUARE (1:1), not 16:9: this image sits on the right half of a slide, beside the text. Fewer, larger elements; every label must stay legible when the square is shown at about 900 px.

Render this as a TOP-TO-BOTTOM flow.

TITLE (top-left): "Coordinator and dispatcher"
SUBTITLE: "The root chooses who takes the conversation, and a transfer hands it over"

TOP: a Purple person box "Dana · store manager" with a white speech bubble "Anything in the coaching signals for Noor?".
  Arrow from Dana down to the root, with circle 1 on it.

MIDDLE: a large Blue box "store_manager_agent" with second line "coordinator · owns the conversation".
  Attached to its right side, one Orange pill "instruction + each sub-agent's description", with circle 2 beside it.

BELOW THE ROOT, two groups side by side:
  LEFT GROUP: one Blue box with a thick border "associate_development" with second line "chat sub-agent · transfer target". Under it, one Yellow gear box "get_coaching_context · get_learning_options". A small Red shield chip on its corner: "role and store checks".
    A thick Blue arrow from the root to "associate_development" labeled "transfer_to_agent", with circle 3 on it.
  RIGHT GROUP: three small Gray boxes stacked, dimmed: "inventory_excellence", "associate_orchestration", "loss_prevention", with one shared Gray caption "called as tools · pattern 2". A thin dashed Gray line joins them to the root. They receive no transfer.

A curved Purple arrow from Dana directly to "associate_development" (bypassing the root), labeled "the next turns go here", with circle 4 on it.
A small Blue note beside "associate_development": "stays active until something transfers again", with circle 5 beside it.

Exactly one person, one root, one transfer target with one tools box, and three dimmed boxes. No other components.

NUMBERED STEPS: small Charcoal circles with a white number ("1" to "5") sit on or beside the arrows they describe, exactly one circle per number, and nothing else is numbered.
NO FOOTER: there is no strip, bar, caption or footer line at the bottom of the canvas. The diagram uses the full height of the square, vertically centred under the title.
The only text on the canvas is the quoted labels above. Every box sits fully inside the canvas with a clear margin; nothing is cropped by the edge. Generous padding; arrows route around boxes; all labels horizontal. Every box is wide enough that its identifier stays on one line and never breaks at an underscore.
TEXT AND COLOR GUARD: the picture contains no text except the double-quoted strings in this description. Words written in capitals here (TITLE, SUBTITLE, TOP, MIDDLE, BOTTOM, LEFT, RIGHT, NUMBERED STEPS, NO FOOTER and the like) are layout instructions and never appear in the picture. In your prompt, name colors only by word (Blue, Yellow, Green, Red, Purple, Orange, Gray, Charcoal) and never write a hex code; describe positions in lowercase prose and never give a region, row, bar or legend a name of its own. A region with no quoted title has no title.
## Crafted image prompt (Step 1 output used for the current render)

A clean, modern technical system architecture diagram in a square 1:1 aspect ratio on a solid pure White background, with generous white space and high-contrast vector elements suitable for technical documentation slides.

At the top-left of the canvas, render the primary title in bold Charcoal text: "Coordinator and dispatcher". Directly below it, render the subtitle in regular Medium Gray text: "The root chooses who takes the conversation, and a transfer hands it over".

Near the top center of the canvas, render a Purple rounded rectangle box displaying a white person silhouette icon and bold white text: "Dana · store manager". Directly adjacent to this box is a white speech bubble with a thin gray outline containing Charcoal text: "Anything in the coaching signals for Noor?".

From the bottom of the "Dana · store manager" box, a straight downward Charcoal arrow connects to the central root box below. Centered along this downward arrow is a small, solid Charcoal circle containing a clean white numeral "1".

In the upper-middle center of the canvas sits the root box: a large Blue rounded rectangle with comfortable internal padding. It contains two lines of horizontal white text: the top line in bold reads "store_manager_agent", and the second line in regular weight reads "coordinator · owns the conversation". The box is sufficiently wide so that the identifier fits entirely on one line without hyphenation. Attached to the right edge of this root box is a horizontal Orange pill-shaped badge containing Charcoal text: "instruction + each sub-agent's description". Positioned immediately beside this Orange pill is a small solid Charcoal circle containing a clean white numeral "2".

Below the root box, arrange two separate columns side by side:

In the lower-left area, render the active transfer target component. A prominent, thick Blue directional arrow leads downward from the root box to this component, labeled with horizontal Blue text: "transfer_to_agent". On this Blue arrow rests a small solid Charcoal circle containing a clean white numeral "3".

The transfer target is a Blue rounded rectangle box with a thick distinct border, containing two lines of horizontal white text: bold "associate_development" on the first line, and regular "chat sub-agent · transfer target" on the second line. Immediately underneath it, visually joined, is a Yellow rounded rectangle box with a small generic gear glyph and horizontal Charcoal text: "get_coaching_context · get_learning_options". Overlapping the top-right corner of this Yellow box is a small Red badge containing a tiny generic shield icon and white text: "role and store checks".

Sweeping from the Purple "Dana · store manager" box at the top, down along the left perimeter and bypassing the central root box, is a smooth curved Purple arrow that points directly into the "associate_development" box. Centered on this curved path is horizontal Purple text reading "the next turns go here", accompanied by a small solid Charcoal circle containing a clean white numeral "4".

To the side of the "associate_development" box is a crisp Blue annotation text label reading "stays active until something transfers again", with a small solid Charcoal circle containing a clean white numeral "5" placed directly beside it.

In the lower-right area, render a dimmed secondary group consisting of three identical, small Light Gray rounded rectangle boxes stacked neatly vertically with Medium Gray borders. Each box displays centered Charcoal text on a single line:
- Top box: "inventory_excellence"
- Middle box: "associate_orchestration"
- Bottom box: "loss_prevention"

A thin, subtle dashed Gray line extends from the right side of the root "store_manager_agent" box down to this stack (no transfer arrowhead). Centered directly beneath the three stacked gray boxes is a shared Medium Gray caption reading: "called as tools · pattern 2".

Visual rules:
- The canvas has no footer, bottom bar, or status strip; the layout is vertically balanced and centered within the square frame with ample external margins.
- All text strings appear in horizontal, clean sans-serif typography and match the quoted wording exactly.
- Exactly five numbered circular step badges ("1", "2", "3", "4", "5") exist across the entire diagram.
- All boxes, pills, and arrows have clean flat geometry, solid fills, and no gradients, 3D effects, or realistic textures.
