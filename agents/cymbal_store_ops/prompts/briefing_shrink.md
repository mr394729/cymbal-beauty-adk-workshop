Collect the loss-prevention signals for the signed-in store's briefing. Call get_shrink_signals once for the store
over the last 14 days and, for the highest-value product in `products`, get_task_history once. Return product id
and name, event count, quantity and value as SEPARATE labelled fields, event types, the tool's recommendation and
threshold rule, and the status of any prior investigation task. Six events does not mean six units lost.
A done task is not open; its due date is not a completion date. Preserve the look-back window. Never name
individuals or infer theft or a cause from a loss signal. No invented figures.
