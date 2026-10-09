# 麦当劳 MCP 工具参考

> 本文件内容来自 **2026-10-10 对官方接口的真实调用**，不是文档推测。
> 凡本文未记载的行为，一律视为「未验证」，不要声称支持。

## 接入

| 项 | 值 |
|---|---|
| 端点 | `https://mcp.mcd.cn/` —— **根路径，不是 `/mcp`** |
| 认证 | Header `Authorization: Bearer <32位Token>` |
| 协议 | MCP Streamable HTTP，`protocolVersion: 2025-06-18` |
| 请求头 | `Accept: application/json, text/event-stream` |
| 状态 | 无状态，`tools/list`、`tools/call` 均不需要 session id |
| Token 申请 | https://open.mcd.cn/mcp （手机号登录 → 控制台 → 激活 → 复制） |
| 工具总数 | **35**（实测 `tools/list` 返回） |

## 本项目使用的工具

| 工具 | 入参（`*` 为必填） |
|---|---|
| `list-nutrition-foods` | （无） |
| `query-nearby-stores` | `beType*`, `searchType*`, `city`, `keyword` |
| `query-meals` | `storeCode*`, `beType*`, `orderType*` |
| `query-meal-detail` | `storeCode*`, `code*`, `beType*`, `orderType*` |
| `calculate-price` | `storeCode*`, `beType*`, `orderType*`, `items` |
| `create-order` | `storeCode*`, `beType*`, `orderType*`, `items` |
| `now-time-info` | （无） |
| `order-list` | （无） |

其余 27 个工具（券、积分、抽奖、派对、麦麦商城、外送地址、团餐助餐等）
不在本项目范围内，本技能**不调用**它们。

## 实测确认的关键行为

### 1. 响应永远是同一层信封

所有工具的 `structuredContent` 都指向同一结构：

```json
{"success": true, "code": 200, "message": "请求成功",
 "datetime": "2026-10-10 01:13:03", "traceId": "...", "data": {...}}
```

**坑**：早期实现以为 `structuredContent` 就是业务数据，直接传给解析器，
结果 `query-meals` 静默解析出 **0 条**。必须先判断信封（含 `success`/`code`）
并剥掉 `data` 一层；`success=false` 时要抛可见错误，不能静默返回空。

### 2. `list-nutrition-foods` 返回 TOON 紧凑格式

`data` 是一个**字符串**，不是数组：

```
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
```

- 实测 **160 条**（不是社区流传的 156 条）
- 字段名和顺序要从头部动态读取，不要硬编码
- **`nutritionDescription` 实测全为 `null`**，无有效信息
- **不返回 `productCode`**，只能按餐品名匹配
- **不覆盖套餐**，套餐的营养无法从该表获得
- 缺失值一律 `null`，**绝不当 0**
- 实测：钠 0–1373 mg，中位数 122 mg

### 3. `query-meals` 是「分类 + 映射」双结构

```json
{"categories":[{"name":"巨无霸","meals":[{"code":"1440"}]}],
 "meals":{"1440":{"name":"麦辣鸡腿汉堡","currentPrice":"22.5","originalPrice":"46"}}}
```

- 分类里的 `meals[].code` 只有编码，**名称在顶层 `meals` 映射里**
- 只遍历 `categories` 会拿到一堆没有名称的条目
- 实测某门店：14 个分类、84 项餐品
- 价格单位是**元**、字符串类型（`"22.5"`）

### 4. `query-meal-detail` 的 `modification` 没有营养字段

实测字段只有：

```
modification.items[].{maxValues, minValues, values[]}
values[].{code, name, price, maxQuantity, minQuantity, selectedQuantity, selectedKey, unselectedKey}
```

**没有任何营养字段。** 因此：

- ✅ 可以做：列出可特制项、判断是否默认包含、计算对**价格**的影响
- ❌ 不能做：「去酱料减少 620 mg 钠」这类量化结论
- 只能给方向性提示（如「酱料通常是钠的主要来源」），并显著标注非量化

实测样例（麦辣鸡腿汉堡，code 1440）：可调项为「麦香鸡酱」「切块生菜」，
价格影响均为 0。

### 5. 门店字段与营业状态

`query-nearby-stores` 返回：
`storeCode, storeName, address, distance, businessStatus, businessStartTime,
businessEndTime, longitude, latitude, reservation, reservationTimeOptions`

- **`businessStatus` 实测是布尔值**（`true`/`false`）
- **坑**：早期实现用 `str()` 强转，`False` 变成字符串 `"False"`，
  无法匹配任何判断分支，导致所有门店都显示「营业状态未知」。必须先判断布尔类型
- **`distance` 单位是米**（实测 52 / 477 / 769 米）
- **不返回任何无障碍设施信息**（无坡道、无无障碍卫生间、无低位柜台）——
  必须向用户明示无法核实，不要编造

### 6. 金额单位不统一

| 来源 | 单位 | 类型 |
|---|---|---|
| `query-meals` | 元 | 字符串 `"22.5"` |
| `calculate-price` | **分** | 整数 `2250` |

`calculate-price` 实测返回 `productPrice/productOriginalPrice/price/discount/productList[]`。

### 7. `items` 字段名必须是 `productCode`

写成 `code`、`mealCode` 等**不报错，只静默返回 `price=0`**。
核价为 0 时必须判定为结构错误，不能当作「免费」。

### 8. 错误码

| 码 | 含义 | 处理 |
|---|---|---|
| `200` | 成功 | — |
| `600057` | 门店可能已关闭或不在营业时间 | 换一家营业中的门店 |
| `600058` | `city`/`keyword` 缺失 | 两者必须同时提供 |

## 未验证 / 未查到

- 限流阈值（文档称 600 次/分钟，本项目未实测到上限）
- `create-order` 的真实下单流程（本项目默认不执行）
- 各门店无障碍设施的实际情况（接口不提供，需人工致电确认）
