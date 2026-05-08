# `/get` 查询接口速查

- Method: `POST`
- Path: `/get`
- Body: JSON
- 必传：`model_code`
- Agent V2 订单查询固定使用：`model_code="super_function"`、`without_meta=true`

## 查询模式

详情查询：传 `_id`，返回 `object`，`objects=null`，`is_in_list=false`。

```json
{
  "model_code": "super_function",
  "_id": "67f0c1111111111111111111",
  "shown_field_codes": ["title", "event_date"],
  "without_meta": true
}
```

列表查询：不传 `_id`，返回 `objects`，`object=null`，`is_in_list=true`。

```json
{
  "model_code": "super_function",
  "current": 1,
  "pageSize": 10,
  "with_total_count": true,
  "without_meta": true,
  "field_filters": {
    "event_date": { "min": "2026-04-01", "max": "2026-04-30" }
  },
  "field_sorts": { "event_date": "desc" },
  "shown_field_codes": ["title", "event_date", "total_fee"]
}
```

## 常用请求参数

- `_id`: 单条详情 id；有 `_id` 时不要传分页参数。
- `current`, `pageSize`: 页码和每页条数。
- `field_filters`: 字段过滤，例如日期范围 `{ "event_date": { "min": "...", "max": "..." } }`。
- `field_sorts`: 排序，例如 `{ "event_date": "desc" }`。
- `search`, `search_field_codes`: 关键字搜索及搜索字段。
- `shown_field_codes`: 限制返回字段，优先使用以减少响应体。
- `with_total_count`: 列表查询时返回总数。
- `without_meta`: 不返回模型、字段、动作等元信息。
- `without_model`, `without_actions`: 更细粒度关闭模型或动作信息。
- `only_deleted`: 只查已删除数据。
- `is_show_latest_foreign`: 刷新外键最新数据。

## 可选高级参数

日历查询：

- `calendar_date_field_code`: 生成日历的日期字段。
- `calendar_month`: 指定月份，格式 `YYYY-MM`。
- `calendar_month_offset`: 相对当前月偏移。
- `remove_head_foot`: 是否裁掉前后补齐周。

统计查询：

- `aggregate_id_field_code`: 分组字段。
- `aggregate_sum_field_code`: 单个求和字段。
- `aggregate_sum_field_codes`: 多个求和字段。
- `aggregate_where`: 统计专用覆盖条件。
- `with_node_cnts`: 返回节点统计。
- `is_force_statistics`: 翻页后仍强制统计。

统计查询用于回答“各状态多少单”“按渠道/销售/状态分布”“总金额/各组金额合计”等问题。返回中重点看 `statistic`、`total_count`、`total_sum`。

示例：筛选订单后按销售状态统计：

```json
{
  "model_code": "super_function",
  "current": 1,
  "pageSize": 50,
  "with_total_count": true,
  "without_meta": true,
  "field_filters": {
    "task_type": { "equal": "MAIN" },
    "is_sample": { "not": true },
    "sales_status": { "equal": "成交" }
  },
  "field_sorts": { "created_at": "desc" },
  "aggregate_id_field_code": "sales_status"
}
```

完整请求中可能还会携带前端分页展示字段或业务动作字段，例如：

```json
{
  "model_code": "super_function",
  "field_sorts": { "created_at": "desc" },
  "field_filters": {
    "task_type": { "equal": "MAIN" },
    "is_sample": { "not": true },
    "sales_status": { "equal": "成交" }
  },
  "current": 1,
  "pageSize": 50,
  "total": 269,
  "showTotal": true,
  "showJumper": true,
  "showPageSize": true,
  "with_total_count": true,
  "action_code": "get_order",
  "aggregate_id_field_code": "sales_status",
  "without_meta": true,
  "project_code": "lighting-designer"
}
```

Agent 生成结构化请求时重点保留查询语义字段：`field_filters`、`field_sorts`、`current`、`pageSize`、`with_total_count`、`aggregate_id_field_code`、`without_meta`。其中 `aggregate_id_field_code` 是触发分组统计的关键字段。

## 返回结构

普通 JSON 返回常见字段：

```json
{
  "object": null,
  "objects": null,
  "total_count": null,
  "total_sum": null,
  "is_in_list": false,
  "statistic": null,
  "node_cnts": null,
  "model": {},
  "query_fields": [],
  "foreign_models": {},
  "model_actions": [],
  "client_action_code": "get_xxx",
  "client_action_name": "查看xxx"
}
```

- `object`: 详情查询结果。
- `objects`: 列表查询结果。
- `total_count`: 总条数。
- `total_sum`: 求和结果。
- `statistic`: 分组统计结果，例如 `{ "_id": "已成交", "cnt": 12, "sum": 56000 }`。
- `node_cnts`: 节点统计结果。
- `query_fields`: 字段定义；字段可能含 `#s` 展示、`#e` 编辑隐藏、`#w` 可写。
- `model`, `foreign_models`, `model_actions`: 元信息；`without_meta=true` 时通常不需要。

导出动作可能返回 Excel 文件流，不是 JSON。
