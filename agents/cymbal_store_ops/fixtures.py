"""Frozen fixtures shared by the data generator, the prompts, the tests and the evals.

Everything the workshop refers to by name lives here so that "Saturday morning", "Priya",
"Lumière Hydra Cream" and "the P-0420 shrink pattern" mean the same thing on every attendee's project.
"""

DATA_VERSION = "2026.09.21-ops2"

# The workshop's frozen clock: Saturday 3 Oct 2026, 09:00 America/Chicago (UTC-5).
FIXTURE_NOW_ISO = "2026-10-03T09:00:00-05:00"
FIXTURE_TIMEZONE = "America/Chicago"
FIXTURE_WEEK = "2026-W39"          # the completed ISO week the coaching signals describe

# ---- the hero store and its people (all guaranteed by data/generate.py) --------------------------
HERO_STORE_ID = "S-014"
HERO_STORE_CITY = "Naperville"
HERO_STORE_NAME = "Cymbal Beauty Naperville"
HERO_MANAGER_ID = "U-M014"                 # Dana, store_manager at S-014
HERO_MANAGER_FIRST_NAME = "Dana"
HERO_ASSOCIATE_ID = "A-1004"               # Priya, associate at S-014, free 09:00-13:00
HERO_ASSOCIATE_FIRST_NAME = "Priya"
HERO_ASSOCIATE_SKILLS = ("bopis", "skincare")
HERO_DISTRICT_MANAGER_ID = "A-1001"        # district_manager whose home store is S-014
COACHING_ASSOCIATE_ID = "A-1007"           # associate at S-014 with a low BOPIS pick rate in FIXTURE_WEEK
COACHING_LOW_PICK_RATE = 0.52

# ---- the OSA exception (inventory excellence) ---------------------------------------------------
HERO_PRODUCT_ID = "P-0101"
HERO_PRODUCT_NAME = "Lumière Hydra Cream"
HERO_STORE_ON_HAND = 7                     # on_hand = on_shelf_qty + backroom_qty, always
HERO_STORE_ON_SHELF = 0
HERO_STORE_BACKROOM = 7
HERO_REORDER_POINT = 12
HERO_SHELF_CAPACITY = 18
HERO_BOPIS_PENDING = 9                     # pending BOPIS orders at S-014 promised by 11:00 on the frozen day
HERO_BOPIS_PENDING_FOR_PRODUCT = 3         # of those, for the hero product

# ---- the shrink pattern (loss prevention) -------------------------------------------------------
SHRINK_PRODUCT_ID = "P-0420"
SHRINK_PRODUCT_NAME = "Noir Velvet Eau de Parfum"   # fragrance, locked case
SHRINK_EVENTS_14D = 6                      # shrink events for P-0420 at S-014 in the last 14 days

# ---- vocabularies ---------------------------------------------------------------------------------
ROLES = ("associate", "store_manager", "district_manager")
SKILLS = ("bopis", "skincare", "fragrance", "makeup", "haircare", "cash_wrap", "backroom")
TASK_TYPES = ("backroom_check", "replenish", "cycle_count", "coverage_move", "investigation",
              "coaching", "planogram_fix", "signage_fix")
TASK_STATUSES = ("open", "done", "cancelled")
TASK_SOURCES = ("agent", "manager", "system")
BOPIS_STATUSES = ("pending", "picked", "ready", "collected")
SHRINK_EVENT_TYPES = ("damage", "unknown_loss", "return_anomaly", "adjustment")
FEEDBACK_TOPICS = ("checkout_wait", "associate_help", "stock", "store_condition", "salon")
COACHING_METRICS = ("bopis_pick_rate", "cycle_count_accuracy", "guest_rating", "task_completion")
REPLENISHMENT_STATUSES = ("scheduled", "in_transit", "received", "delayed")

BRANDS = (
    "Lumière Skin", "Velvet Root", "Aurelia Cosmetics", "Brightside Naturals",
    "Meridian Fragrance", "Tidewater Botanicals", "Noor Beauty", "Cymbal Collection",
)

EXPECTED_ROW_COUNTS = {
    "products": 600, "reviews": 6000, "stores": 40, "store_inventory": 24000,
    "associates": 200, "store_tasks": 400, "bopis_orders": 2000, "store_traffic": 6720,
    "shrink_events": 1500, "guest_feedback": 800, "coaching_signals": 624, "replenishment": 1200, "operations_context": 16,
}
