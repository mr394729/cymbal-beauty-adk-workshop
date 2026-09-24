"""The quickstart catalog tests are offline: a fixed namespace whatever .env says."""
from __future__ import annotations

import os

os.environ["WORKSHOP_NAMESPACE"] = "unit"
