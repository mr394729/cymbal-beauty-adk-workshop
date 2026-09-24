# pattern-5-iterative-refinement

**Title:** Pattern 5 · Iterative refinement — the one-pager diagram (text on the left of the slide, this image on the right)

**Aspect:** 1:1

**Creative direction:** `_creative_direction.md` (Google Cloud palette, Cymbal Beauty branding, no logos)

**Pipeline:** gemini-diagramming. Step 1 `gemini-3.8-flash` (thinking HIGH) crafts the image prompt from the description below; Step 2 `gemini-3.1-flash-image` renders 1:1 at `image_size=4K` with thinking off. The numbered circles match the "Agentic flow" steps on the one-pager (see `docs/patterns/README.md`).

**Source of truth:** `quickstarts/10-multi-agent-router/patterns/04_loop_generate_review.py`

## Description (Step 1 input — edit this to regenerate)

The canvas is SQUARE (1:1), not 16:9: this image sits on the right half of a slide, beside the text. Fewer, larger elements; every label must stay legible when the square is shown at about 900 px.

Render this as a CYCLE inside one region, with the exit on the right.

TITLE (top-left): "Iterative refinement"
SUBTITLE, written exactly, letter for letter, in one regular weight with no bold words: "A writer and a critic repeat until the rubric holds or the limit is reached"

A large light-blue region with a solid Blue border titled "LoopAgent · huddle_note · max_iterations 3".
Inside it, two Blue boxes facing each other:
  LEFT: "huddle_writer" with second line "writes huddle_draft". Under it, one Yellow gear box "get_traffic_and_backlog · get_shift_roster". Circle 1 beside it.
  RIGHT: "huddle_critic" with second line "writes huddle_review".
  EXACTLY ONE Blue arrow goes from "huddle_writer" to "huddle_critic", straight across, labeled "huddle_draft", with circle 2 on it. There is no second Blue arrow between them.
  EXACTLY ONE Red curved arrow goes from the bottom of "huddle_critic" back to the bottom of the "huddle_writer" box itself (not to the tools box), labeled "what failed, and the fix", with circle 4 on it.
  Beside the critic, a white rubric card with a Charcoal border titled "Rubric" with four short lines: "1 names a count from the tools", "2 every associate id came from a tool", "3 under 60 words", "4 no HR language".

RIGHT, outside the region: a Green arrow leaving the critic labeled "exit_loop", with circle 3 on it, ending at a white card "Accepted huddle note".
Below it, a Gray arrow leaving the bottom of the region labeled "third pass ends", with circle 5 on it, ending at a Gray card "last draft, never accepted: handle it".

Exactly two agents, one tools box, one rubric card and two outcome cards. No other components.

NUMBERED STEPS: small Charcoal circles with a white number ("1" to "5") sit on or beside the arrows they describe, exactly one circle per number, and nothing else is numbered.
NO FOOTER: there is no strip, bar, caption or footer line at the bottom of the canvas. The diagram uses the full height of the square, vertically centred under the title.
The only text on the canvas is the quoted labels above. Every box sits fully inside the canvas with a clear margin; nothing is cropped by the edge. Generous padding; arrows route around boxes; all labels horizontal. Every box is wide enough that its identifier stays on one line and never breaks at an underscore.
TEXT AND COLOR GUARD: the picture contains no text except the double-quoted strings in this description. Words written in capitals here (TITLE, SUBTITLE, TOP, MIDDLE, BOTTOM, LEFT, RIGHT, NUMBERED STEPS, NO FOOTER and the like) are layout instructions and never appear in the picture. In your prompt, name colors only by word (Blue, Yellow, Green, Red, Purple, Orange, Gray, Charcoal) and never write a hex code; describe positions in lowercase prose and never give a region, row, bar or legend a name of its own. A region with no quoted title has no title.
## Crafted image prompt (Step 1 output used for the current render)

A professional, clean software architecture diagram on a square 1:1 canvas with a pure white background. The aesthetic is modern, minimal, flat technical documentation style with generous padding, crisp vector lines, and no gradients, 3D effects, or drop shadows. All text must be horizontal and rendered cleanly using a geometric sans-serif typeface.

At the top-left of the square canvas:
- Main title in bold Charcoal: "Iterative refinement"
- Directly beneath the title, a single-line subtitle in uniform regular weight Charcoal text: "A writer and a critic repeat until the rubric holds or the limit is reached"

Occupying the central-left area is a large rounded-corner container with a soft Light Blue fill and a solid Blue border. At the top-left inside this container, display the container title in bold Blue: "LoopAgent · huddle_note · max_iterations 3".

Inside this Light Blue container, place two primary agent boxes facing each other:
1. On the left side of the container: A solid Blue rounded rectangle with white text. First line in bold: "huddle_writer", second line in regular weight: "writes huddle_draft".
   - Directly underneath the writer box sits a bright Yellow rounded rectangle with a small generic gear icon glyph and Charcoal text on a single line: "get_traffic_and_backlog · get_shift_roster".
   - Beside this yellow tools box sits a small solid Charcoal circular badge containing the numeral "1" in white.
2. On the right side of the container: A solid Blue rounded rectangle with white text matching the writer in size. First line in bold: "huddle_critic", second line in regular weight: "writes huddle_review".
   - Next to the critic box inside the container, place a clean white card with a crisp Charcoal border. The card header reads "Rubric" in bold Charcoal, followed by four cleanly formatted horizontal bullet lines in regular Charcoal text:
     "1 names a count from the tools"
     "2 every associate id came from a tool"
     "3 under 60 words"
     "4 no HR language"

Connections inside the loop:
- A single straight horizontal Blue arrow points directly from the right edge of "huddle_writer" to the left edge of "huddle_critic". Above this arrow is the label "huddle_draft" in Blue text. On this arrow sits a small solid Charcoal circular badge containing the numeral "2" in white.
- A single smooth curved Red arrow originates from the bottom edge of "huddle_critic", curves downward and loops back across to connect to the bottom edge of the "huddle_writer" box (routing cleanly clear of the yellow tools box). Along this red feedback path is the label "what failed, and the fix" in Red text, accompanied by a small solid Charcoal circular badge containing the numeral "4" in white.

Exits and outcome cards on the right side of the canvas, outside the Light Blue container:
1. From the right edge of the "huddle_critic" box, a solid Green arrow points rightward, breaking out of the container. Above the arrow is the label "exit_loop" in Green text, with a small solid Charcoal circular badge containing the numeral "3" in white. This arrow terminates at a white rectangular card with a solid Green border containing the centered text in bold Green: "Accepted huddle note".
2. Exiting from the lower-right boundary of the main container, a solid Gray arrow points rightward and downward. Above the arrow is the label "third pass ends" in Medium Gray text, with a small solid Charcoal circular badge containing the numeral "5" in white. This arrow terminates at a soft Light Gray rectangular card with a Medium Gray border containing the centered text in Charcoal: "last draft, never accepted: handle it".

Composition details:
- Square aspect ratio (1:1).
- The layout is balanced and vertically centered under the title, utilizing the full canvas height with wide margins so no box touches the edges.
- Absolutely no footer bar, caption bar, or baseline divider at the bottom.
- The diagram contains exactly two agents, one tools box, one rubric card, and two outcome cards.
- Numbered circular badges appear strictly as the numerals 1, 2, 3, 4, and 5 corresponding to the described steps.
- Only the exact quoted text appears in the illustration, with all box labels wide enough to fit on single lines without breaking underscores.
