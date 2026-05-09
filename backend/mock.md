Is the order sales status in 2026 better than in 2025 in terms of order count and income amount?
Conclusion: Yes. Based on the available order statistics, 2026 performs better than 2025 on both order count and income amount. The 2026 order count is 186 orders, which is 43 orders higher than 2025 and represents 30.1% year-over-year growth. The 2026 income amount is 1,092,120, which is 320,160 higher than 2025 and represents 41.5% year-over-year growth. Average income amount per order also improves from 5,398.32 in 2025 to 5,871.61 in 2026, so the improvement is not only more orders but also stronger income amount per order.

What is the order count for 2026?
Reason: The root question needs the 2026 order count as the first comparison metric. Order count is calculated from the count of non-sample MAIN orders with `order_time` in 2026.
Conclusion: The order count for 2026 is 186 orders.

What is the order count for 2025?
Reason: The root question needs the 2025 order count as the baseline for comparison with 2026. Order count is calculated from the count of non-sample MAIN orders with `order_time` in 2025.
Conclusion: The order count for 2025 is 143 orders.

What is the income amount for 2026?
Reason: The root question also needs the 2026 income amount to compare actual received payment performance. Income is calculated from the sum of `paid_fee` for non-sample MAIN orders with `order_time` in 2026.
Conclusion: The income amount for 2026 is 1,092,120.

What is the income amount for 2025?
Reason: The root question needs the 2025 income amount as the baseline for comparing received payment performance. Income is calculated from the sum of `paid_fee` for non-sample MAIN orders with `order_time` in 2025.
Conclusion: The income amount for 2025 is 771,960.

What is the order count for 2026?
Raw data:
{
  "request": {
    "model_code": "super_function",
    "without_meta": true,
    "current": 1,
    "pageSize": 1,
    "with_total_count": true,
    "field_filters": {
      "task_type": { "equal": "MAIN" },
      "is_sample": { "not": true },
      "order_time": { "min": "2026-01-01", "max": "2026-12-31" }
    },
    "shown_field_codes": ["order_time", "title"]
  },
  "result": {
    "total_count": 186,
    "objects": []
  }
}
Conclusion: The 2026 order query returned 186 MAIN non-sample orders. This order count is used in the root comparison.

What is the order count for 2025?
Raw data:
{
  "request": {
    "model_code": "super_function",
    "without_meta": true,
    "current": 1,
    "pageSize": 1,
    "with_total_count": true,
    "field_filters": {
      "task_type": { "equal": "MAIN" },
      "is_sample": { "not": true },
      "order_time": { "min": "2025-01-01", "max": "2025-12-31" }
    },
    "shown_field_codes": ["order_time", "title"]
  },
  "result": {
    "total_count": 143,
    "objects": []
  }
}
Conclusion: The 2025 order query returned 143 MAIN non-sample orders. This order count is the 2025 baseline.

What is the income amount for 2026?
Raw data:
{
  "request": {
    "model_code": "super_function",
    "without_meta": true,
    "current": 1,
    "pageSize": 1,
    "with_total_count": true,
    "field_filters": {
      "task_type": { "equal": "MAIN" },
      "is_sample": { "not": true },
      "order_time": { "min": "2026-01-01", "max": "2026-12-31" }
    },
    "aggregate_sum_field_code": "paid_fee",
    "shown_field_codes": ["order_time", "title", "paid_fee"]
  },
  "result": {
    "total_count": 186,
    "total_sum": {
      "paid_fee": 1092120
    },
    "currency": "CNY"
  }
}
Conclusion: The 2026 order query returned summed `paid_fee` of 1,092,120. Against the 2026 order count of 186 orders, this implies average income amount of 5,871.61 per order.

What is the income amount for 2025?
Raw data:
{
  "request": {
    "model_code": "super_function",
    "without_meta": true,
    "current": 1,
    "pageSize": 1,
    "with_total_count": true,
    "field_filters": {
      "task_type": { "equal": "MAIN" },
      "is_sample": { "not": true },
      "order_time": { "min": "2025-01-01", "max": "2025-12-31" }
    },
    "aggregate_sum_field_code": "paid_fee",
    "shown_field_codes": ["order_time", "title", "paid_fee"]
  },
  "result": {
    "total_count": 143,
    "total_sum": {
      "paid_fee": 771960
    },
    "currency": "CNY"
  }
}
Conclusion: The 2025 order query returned summed `paid_fee` of 771,960. Against the 2025 order count of 143 orders, this implies average income amount of 5,398.32 per order.
