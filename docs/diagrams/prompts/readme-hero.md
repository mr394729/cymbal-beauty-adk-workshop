# readme-hero

**Slide:** none (the first image on the repository README)

**Aspect:** 16:9

**Pipeline:** `uv run --with pillow --with google-genai python ../render.py --dir . readme-hero` (Gemini house style, Google Cloud palette, no logos).

**Source of truth:** `README.md`, `notebooks/`, `quickstarts/`, `agents/cymbal_store_ops/mcp_catalog.py`, `frontend/`

## Description (Step 1 input — edit this to regenerate)

The canvas is 16:9. This is the INFOGRAPHIC that opens a developer repository page: bold, colorful and friendly,
with large numbers and simple flat icons, still clean and technical. It has ONE title at the top left and no footer.
Every label must stay legible when the image is shown about 1000 px wide. Fewer, larger elements.

TITLE, top left, very large bold Charcoal: "Build a store operations agent with ADK", and under it one smaller regular
Medium Gray line: "Cymbal Beauty workshop · three hours · eight notebooks".

MIDDLE BAND, the story from left to right, three large cards joined by two thick arrows:
  CARD ONE, a Purple card with a simple flat tablet icon showing a chat bubble: bold "Ask", smaller line
  "a store manager asks a question on the tablet".
  CARD TWO, the largest, a Blue card with a flat icon of one big node linked to three small nodes: bold "Reason",
  smaller line "an ADK coordinator and specialists plan the answer".
  CARD THREE, a Green card with a flat database icon behind a small shield: bold "Read", smaller line "every store
  read goes through an MCP server to BigQuery".
  The first arrow is labeled "one session", the second "30 MCP tools".

NUMBERS ROW, under the middle band, five big bold numbers, each with one small plain line under it, evenly spaced:
  Blue "8" with "notebook labs", Orange "12" with "quickstarts", Yellow "30" with "MCP tools", Green "5" with
  "ADK patterns in the agent", Red "1" with "gate before every release".

BOTTOM STRIP, one thin horizontal timeline across the full width with four colored segments and a small label on
each: Blue "Build", Yellow "Evaluate", Green "Deploy", Red "Govern", with the small Medium Gray caption at its right
end "notebooks 00 to 07".

Exactly one title with one subtitle line, three cards, two arrows, five numbers and one timeline. No other text.

The only text on the canvas is the quoted labels above. Every element sits fully inside the canvas with a clear
margin; nothing is cropped by the edge. Generous white space; all labels horizontal.
NO HEADINGS GUARD: no card, row or strip has any heading, caption or label beyond the quoted text. Never describe a
component in the prompt by a made-up role name; refer to each only by its quoted text.
TEXT AND COLOR GUARD: the picture contains no text except the double-quoted strings in this description, and no
retailer or vendor name or logo. Words written in capitals here (TITLE, MIDDLE BAND, CARD, NUMBERS ROW, BOTTOM STRIP
and the like) are layout instructions and never appear in the picture. In your prompt, name colors only by word
(Blue, Yellow, Green, Red, Purple, Orange, Gray, Charcoal) and never write a hex code.
## Crafted image prompt (Step 1 output used for the current render)

A high-resolution 16:9 technical infographic slide on a solid crisp White background, designed in a clean, modern, flat vector illustration style with generous white space and bold, readable typography.

At the top left of the canvas, leaving ample margin from the edges:
- A prominent diagram title in extra-large, bold Charcoal text: "Build a store operations agent with ADK"
- Directly beneath it, a single subtitle line in medium, regular-weight Medium Gray text: "Cymbal Beauty workshop · three hours · eight notebooks"

Across the center of the canvas, three large rounded-corner cards are arranged horizontally from left to right, linked by thick directional arrows:
1. The left card has a solid Purple fill with rounded corners. At its center top is a clean, minimalist flat white icon of a tablet device displaying a simple chat bubble. Below the icon is bold white text: "Ask", followed underneath by smaller regular white text: "a store manager asks a question on the tablet".
2. A thick horizontal directional arrow points from the left card to the center card, with a centered horizontal label above the arrow in Medium Gray text: "one session".
3. The center card is slightly larger and taller than the side cards, with a solid Blue fill and rounded corners. At its center top is a clean, minimalist flat white icon depicting a single primary orchestrator node connected by lines to three smaller child nodes. Below the icon is bold white text: "Reason", followed underneath by smaller regular white text: "an ADK coordinator and specialists plan the answer".
4. A thick horizontal directional arrow points from the center card to the right card, with a centered horizontal label above the arrow in Medium Gray text: "30 MCP tools".
5. The right card has a solid Green fill with rounded corners. At its center top is a clean, minimalist flat white icon showing a database cylinder paired with a small flat security shield. Below the icon is bold white text: "Read", followed underneath by smaller regular white text: "every store read goes through an MCP server to BigQuery".

Positioned below the three cards, a horizontal row of five evenly spaced numerical metrics aligned across the width:
1. A very large, bold Blue number "8" positioned directly above a centered line of regular Charcoal text: "notebook labs"
2. A very large, bold Orange number "12" positioned directly above a centered line of regular Charcoal text: "quickstarts"
3. A very large, bold Yellow number "30" positioned directly above a centered line of regular Charcoal text: "MCP tools"
4. A very large, bold Green number "5" positioned directly above a centered line of regular Charcoal text: "ADK patterns in the agent"
5. A very large, bold Red number "1" positioned directly above a centered line of regular Charcoal text: "gate before every release"

Near the bottom of the canvas, spanning horizontally across the width:
- A sleek, thin segmented process bar divided into four adjoining colored segments:
  - The first segment is solid Blue with centered bold white text: "Build"
  - The second segment is solid Yellow with centered bold Charcoal text: "Evaluate"
  - The third segment is solid Green with centered bold white text: "Deploy"
  - The fourth segment is solid Red with centered bold white text: "Govern"
- Immediately to the right of the red segment, horizontally aligned with the bar, a small regular Medium Gray text label: "notebooks 00 to 07"

Style requirements:
- Strictly flat 2D graphic design, sharp lines, zero 3D effects, no glossy reflections, no photorealism, and no gradients.
- All text strings must be perfectly horizontal, crisp, correctly spelled, and strictly limited to the quoted text above.
- No company logos, no third-party branding, no vendor symbols, and no additional captions or structural header words on the canvas.
