"""Assert that the designated invariant rejected an injected fault."""
from __future__ import annotations

import re


def fault_was_detected(message: str, metric: str, required_threshold: float = 1.0) -> bool:
    """ADK reports the mean across cases/runs, including nonapplicable cases.

    A score below the unchanged required threshold proves rejection. Requiring
    zero incorrectly rejects valid failures when unaffected cases score one.
    Other failed metrics, unavailable scores and a lowered threshold do not count.
    """
    pattern = rf"^{re.escape(metric)} for .+ Failed\. Expected ([0-9.]+), but got ([0-9.]+)\.$"
    for line in message.splitlines():
        match = re.fullmatch(pattern, line.strip())
        if match:
            try:
                expected, actual = map(float, match.groups())
            except ValueError:
                continue
            if expected == required_threshold and 0 <= actual < required_threshold:
                return True
    return False
