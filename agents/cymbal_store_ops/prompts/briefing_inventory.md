Collect the inventory signals for the signed-in store's briefing. Make exactly two tool calls: get_osa_exceptions
(limit 3) and get_bopis_demand once for the whole store (no product id). Reply with at most three lines, one per
exception: product id and name, on-shelf / backroom / on-hand versus reorder point, that product's row in the
BOPIS tool's `by_product` written as "N orders (M units)" and "0 orders" when the product is not listed there, and
that product's earliest_promise and latest_promise from the same by_product entry, and the recommended action
from the tool. Preserve the full product-level time range; do not substitute the store-wide pickup window or
state that every order is due at the earliest time. When by_product_complete or promise_times_complete is false,
identify that limitation instead of presenting the returned rows as the complete demand. Never count or add up anything yourself: `orders` and `units` are given to
you separately and an order is not a unit. No prose, no greetings, no invented numbers.
