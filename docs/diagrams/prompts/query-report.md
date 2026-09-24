# query-report

**Slide:** none (repository diagram: docs/ARCHITECTURE.md, tools/README.md, notebook 03)

**Aspect:** 16:9

**Pipeline:** gemini-diagramming. Step 1 `gemini-3.8-flash` (thinking HIGH) crafts the image prompt from the description below; Step 2 `gemini-3.1-flash-image` renders 16:9 at `image_size=4K` with thinking off. Creative direction: `_creative_direction.md`. The page supplies the title and the copy, so the image carries no title.

**Source of truth:** `agents/cymbal_store_ops/tools/store_query.py`, `report_delivery.py`, `callbacks.py`, `frontend/static/reports.js`

## Description (Step 1 input — edit this to regenerate)

The canvas is 16:9. This image sits under a heading on a documentation page, so the image has NO title, NO subtitle and NO footer. Fewer, larger elements; every label must stay legible when the image is shown about 900 px wide.

TWO TEXT LEVELS: a box has a bold name and, where given, one or two smaller regular lines under it.

Render this as THREE COLUMNS left to right, joined by exactly two thick right-pointing arrows, with one wide strip underneath.

LEFT COLUMN, one tall rounded box with a light blue fill and a Blue border. Bold name "The model chooses the query", smaller lines: "reads the schema of nine resources", "picks fields, filters, grouping and measures", "no question-to-tool lookup table". Inside the box at the bottom, one small White chip with a Blue border: "query_store_data".

MIDDLE COLUMN, one tall rounded box with a light red fill and a Red border and a padlock glyph at its top left. Bold name "Code enforces the boundary", smaller lines: "fields and filter values validated", "the signed-in store and role added in code", "one store never reads another". Inside the box at the bottom, one small White chip with a Red border: "before_tool callbacks".

RIGHT COLUMN, two stacked rounded boxes. The upper one has a light green fill and a Green border, bold name "Answer", smaller lines: "a bounded page of rows", "the full matching count". The lower one has a light yellow fill and a Yellow border, bold name "Report", smaller lines: "up to 5,000 rows go to the app", "search, sort, CSV", "the model gets only the metadata". Inside the lower box at the bottom, one small White chip with a Yellow border: "deliver_store_report".

Between the left and middle columns one thick Charcoal arrow pointing right with the small label "query plan". Between the middle and right columns one thick Charcoal arrow pointing right with the small label "rows from BigQuery"; it forks so it reaches both right-column boxes.

BOTTOM, one thin Gray strip across the full width: "a partial report is never described as the whole result".

Exactly four boxes, three chips, two arrows and one strip. No other components.

The only text on the canvas is the quoted labels above. Every box sits fully inside the canvas with a clear margin; nothing is cropped by the edge. Generous padding; arrows route around boxes; all labels horizontal. Every box is wide enough that its label stays on one line and an identifier never breaks at an underscore.
TEXT AND COLOR GUARD: the picture contains no text except the double-quoted strings in this description, and no retailer or vendor name or logo. Words written in capitals here (TOP, MIDDLE, BOTTOM, LEFT, RIGHT, CENTER, ROW, COLUMN, LANE and the like) are layout instructions and never appear in the picture. In your prompt, name colors only by word (Blue, Yellow, Green, Red, Purple, Orange, Gray, Charcoal) and never write a hex code; describe positions in lowercase prose and never give a region, row, bar or legend a name of its own. A region with no quoted title has no title.
## Crafted image prompt (Step 1 output used for the current render)

A high-resolution, professional technical system architecture diagram in a clean, modern flat vector style on a solid white 16:9 canvas. The overall diagram has no title, no subtitle, and no footer, leaving generous white space around all components.

The layout consists of three columns arranged horizontally from left to right, followed by a single full-width horizontal bar across the bottom:

1. Left Column:
   - A single tall rounded rectangle with a very light blue fill and a solid Blue outline border.
   - Inside at the top, a bold Charcoal heading: "The model chooses the query".
   - Immediately below the heading, three smaller regular Charcoal text lines, each on its own line:
     "reads the schema of nine resources"
     "picks fields, filters, grouping and measures"
     "no question-to-tool lookup table"
   - At the bottom inside this box, a small horizontal rectangular white tag with a solid Blue border containing monospace Charcoal text: "query_store_data".

2. Connection from Left to Middle:
   - A single thick horizontal Charcoal arrow pointing right from the left box to the middle box.
   - Above the arrow, centered horizontal Charcoal text: "query plan".

3. Middle Column:
   - A single tall rounded rectangle matching the height of the left box, with a very light red fill and a solid Red outline border.
   - At the top-left inside this box, a small generic outline padlock icon in Charcoal.
   - Next to the icon, a bold Charcoal heading: "Code enforces the boundary".
   - Below the heading, three smaller regular Charcoal text lines, each on its own line:
     "fields and filter values validated"
     "the signed-in store and role added in code"
     "one store never reads another"
   - At the bottom inside this box, a small horizontal rectangular white tag with a solid Red border containing monospace Charcoal text: "before_tool callbacks".

4. Connection from Middle to Right:
   - A single thick horizontal Charcoal arrow extending right from the middle box, which smoothly forks into two branches pointing toward the two stacked boxes on the right.
   - Above the main stem of the arrow, centered horizontal Charcoal text: "rows from BigQuery".

5. Right Column:
   - Two vertically stacked rounded rectangles aligned with the top and bottom of the middle box:
   - Upper Box:
     - Very light green fill with a solid Green outline border.
     - Inside, a bold Charcoal heading: "Answer".
     - Below the heading, two smaller regular Charcoal text lines:
       "a bounded page of rows"
       "the full matching count"
   - Lower Box:
     - Very light yellow fill with a solid Yellow outline border.
     - Inside, a bold Charcoal heading: "Report".
     - Below the heading, three smaller regular Charcoal text lines:
       "up to 5,000 rows go to the app"
       "search, sort, CSV"
       "the model gets only the metadata"
     - At the bottom inside this box, a small horizontal rectangular white tag with a solid Yellow border containing monospace Charcoal text: "deliver_store_report".

6. Bottom Bar:
   - A slender, wide rounded horizontal strip with a light Gray fill running horizontally beneath all three columns with generous separation.
   - Centered inside the strip, horizontal regular Charcoal text:
     "a partial report is never described as the whole result"

Style details:
- Crisp geometric sans-serif typography for all headings and text; monospace font strictly for the three inner tag labels.
- All text strings must appear exactly as quoted, perfectly horizontal, legible, and uncropped.
- Flat 2D vector graphics with clean lines, subtle solid flat edges, no gradients, no 3D effects, no drop shadows, and no decorative textures.
- Absolutely no vendor logos, product icons, or extraneous labels.
