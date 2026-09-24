Collect the coverage and guest signals for the signed-in store's briefing. Call get_traffic_and_backlog for the
next four hours, get_shift_roster for the same four-hour window with focus bopis, and get_guest_feedback for the
last seven days, once each. Return a compact factual report containing:
- query window and the traffic peak hour/visitors from the hourly rows;
- pending BOPIS count and BOTH earliest_promise and latest_promise, labelled as the pickup promise window;
- recommended_assignee_id, first name, matching skill, shift end and current task; whether the candidate covers
  the window, and any other available candidate if returned;
- guest feedback count, average rating, low ratings by topic and a representative returned comment.
The latest promise is not the first deadline; the query-window end is not a pickup deadline. Traffic is a
forecast. Do not invent minimum staffing, capacity or causal explanations for a guest comment. Label unknown
fields as unknown. No actions are executed by this report.

Read get_coverage_requirements alongside roster and backlog. Include actual protected coverage and breaks.
Account for assigned_tasks as commitments; do not call their owner unassigned. Propose a handover if a break
falls within the assignment. Estimate workload only from the provided planning estimates.
