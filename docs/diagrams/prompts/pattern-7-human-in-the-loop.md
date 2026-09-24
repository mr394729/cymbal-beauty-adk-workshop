# pattern-7-human-in-the-loop

**Title:** Pattern 7 · Human-in-the-loop — the one-pager diagram (text on the left of the slide, this image on the right)

**Aspect:** 1:1

**Creative direction:** `_creative_direction.md` (Google Cloud palette, Cymbal Beauty branding, no logos)

**Pipeline:** gemini-diagramming. Step 1 `gemini-3.8-flash` (thinking HIGH) crafts the image prompt from the description below; Step 2 `gemini-3.1-flash-image` renders 1:1 at `image_size=4K` with thinking off. The numbered circles match the "Agentic flow" steps on the one-pager (see `docs/patterns/README.md`).

**Source of truth:** `agents/cymbal_store_ops/sub_agents/store_tasks.py`, `tools/domain_tools.py` (`create_store_task`, `delegate_task`, `request_confirmation`), `tools/personal_tools.py`

## Description (Step 1 input — edit this to regenerate)

The canvas is SQUARE (1:1), not 16:9: this image sits on the right half of a slide, beside the text. Fewer, larger elements; every label must stay legible when the square is shown at about 900 px.

Render this as a LEFT-TO-RIGHT flow that splits into two outcomes.

TITLE (top-left): "Human-in-the-loop"
SUBTITLE: "The write tool pauses and shows the person exactly what will change"

The main chain runs LEFT TO RIGHT in one row: the Yellow tools box, then the Red padlock box, then the tablet. EXACTLY ONE Red arrow goes from the Yellow box to the Red padlock box, with circle 2 on it, and EXACTLY ONE Red arrow goes from the Red padlock box to the tablet. There is no arrow from the Yellow box directly to the tablet. The word "tools" never appears on the canvas.

LEFT: a Blue box "store_tasks" with second line "task mode · the only write path". Directly under it, one Yellow gear box "create_store_task · delegate_task". A Blue arrow from "store_tasks" down into the Yellow box, with circle 1 on it.

CENTER: a Red padlock box "request_confirmation" with second line "validated payload · invocation pauses", on the same horizontal line as the Yellow box.
  To its right, a simple tablet outline (Charcoal frame, no brand marks) showing a white confirmation card titled "Create task?" with four short lines: "backroom_check", "Lumière Hydra Cream · P-0101", "assign A-1004", "due 10:00", and two buttons: a Green "Approve" and a Gray "Decline". A Purple person glyph "Dana" beside the tablet. Circle 3 beside the card.

RIGHT, two outcomes stacked:
  TOP: a Green arrow from "Approve" labeled "the write runs once · idempotency key", with circle 4 on it, into a Green database cylinder "store_tasks table".
  BOTTOM: a Gray arrow from "Decline" labeled "nothing written · no retry", with circle 5 on it, ending at a Gray card "the action ends".

Under the Yellow box, one small Red shield chip: "managers create and delegate · associates update their own tasks".

Exactly one agent, one tools box, one padlock box, one tablet card, one cylinder and one Gray card. No other components.

NUMBERED STEPS: small Charcoal circles with a white number ("1" to "5") sit on or beside the arrows they describe, exactly one circle per number, and nothing else is numbered.
NO FOOTER: there is no strip, bar, caption or footer line at the bottom of the canvas. The diagram uses the full height of the square, vertically centred under the title.
The only text on the canvas is the quoted labels above. Every box sits fully inside the canvas with a clear margin; nothing is cropped by the edge. Generous padding; arrows route around boxes; all labels horizontal. Every box is wide enough that its identifier stays on one line and never breaks at an underscore.
TEXT AND COLOR GUARD: the picture contains no text except the double-quoted strings in this description. Words written in capitals here (TITLE, SUBTITLE, TOP, MIDDLE, BOTTOM, LEFT, RIGHT, NUMBERED STEPS, NO FOOTER and the like) are layout instructions and never appear in the picture. In your prompt, name colors only by word (Blue, Yellow, Green, Red, Purple, Orange, Gray, Charcoal) and never write a hex code; describe positions in lowercase prose and never give a region, row, bar or legend a name of its own. A region with no quoted title has no title.
## Crafted image prompt (Step 1 output used for the current render)

A clean, professional technical system flow diagram in a flat modern 2D vector style, set on a solid White square 1:1 aspect ratio canvas with generous padding.

At the top-left of the canvas, render a clean title and subtitle:
- Bold Charcoal title: "Human-in-the-loop"
- Regular Charcoal subtitle directly below: "The write tool pauses and shows the person exactly what will change"

The diagram layout is organized left-to-right, vertically centered within the square canvas, splitting into two stacked outcomes on the right:

1. Left side, upper element:
   - A primary Blue rounded rectangle representing the orchestrating agent, with crisp white text displaying "store_tasks" on the top line in bold, and "task mode · the only write path" on the second line in regular font.
   - Directly underneath this Blue box, a vertical Blue arrow points downward into the yellow tool box below it. A small Charcoal circle with a white number "1" is centered on this downward arrow.

2. Left side, middle element:
   - Directly below the agent, a Yellow rounded rectangle containing a subtle generic gear icon on the left, followed by Charcoal text on a single line reading "create_store_task · delegate_task".
   - Directly beneath this Yellow box, a compact Red pill-shaped chip with a tiny shield icon displays crisp Charcoal text reading: "managers create and delegate · associates update their own tasks".

3. Horizontal workflow connection (Center-left to Center):
   - From the right side of the Yellow gear box, exactly one horizontal Red arrow points directly into a Red confirmation box. Centered on this Red arrow is a small Charcoal circle with a white number "2".
   - The Red confirmation box is a rounded rectangle with a solid Red fill, featuring a simple white padlock glyph on the left. The text inside is white: first line bold "request_confirmation", second line regular "validated payload · invocation pauses".

4. Human review interface (Center):
   - Exactly one horizontal Red arrow extends from the right edge of the Red padlock box directly to a tablet interface.
   - The tablet is drawn as a minimal Charcoal device frame with rounded corners and a white screen.
   - Floating just beside the tablet is a Purple circular person glyph with the Purple text label "Dana" next to it.
   - On the tablet screen, display a clean white review card. Beside this card sits a small Charcoal circle with a white number "3".
   - Inside the white review card, top header text in bold Charcoal reads: "Create task?".
   - Below the header are four distinct horizontal text lines in Charcoal:
     - Line 1: "backroom_check"
     - Line 2: "Lumière Hydra Cream · P-0101"
     - Line 3: "assign A-1004"
     - Line 4: "due 10:00"
   - At the bottom of the card sit two action buttons:
     - Left button: Green rounded rectangle with bold white text "Approve".
     - Right button: Medium Gray rounded rectangle with bold white text "Decline".

5. Right side (Two stacked outcomes):
   - Top branch (Approved outcome):
     - Originating directly from the Green "Approve" button, a Green arrow extends rightward and bends toward the upper-right corner.
     - Centered on this Green arrow is a small Charcoal circle with a white number "4", accompanied by horizontal Green text along the path reading "the write runs once · idempotency key".
     - The Green arrow terminates at a Green database cylinder icon labeled with bold white text "store_tasks table".
   - Bottom branch (Declined outcome):
     - Originating directly from the Gray "Decline" button, a Gray arrow extends rightward toward the lower-right corner.
     - Centered on this Gray arrow is a small Charcoal circle with a white number "5", accompanied by horizontal Gray text along the path reading "nothing written · no retry".
     - The Gray arrow terminates at a flat Gray rounded rectangle card labeled with Charcoal text "the action ends".

Visual standards and constraints:
- Minimalist developer documentation aesthetic with high contrast and legible typography even at smaller sizes.
- Exactly five numbered circles ("1", "2", "3", "4", "5") in Charcoal with white digits.
- Exactly one Blue box, one Yellow box, one Red chip, one Red padlock box, one tablet interface, one Green cylinder, and one Gray card.
- No other text, brand logos, realistic photos, gradients, or decorative clutter appears on the canvas. No bottom footer line or banner. All text is strictly horizontal and matches the quoted strings exactly.
