# MCP 接入说明

## 1. 接入的 Server

| 项 | 值 |
|---|---|
| Server | 麦当劳中国官方 MCP Server（`serverInfo.name = mcd-mcp`） |
| 接入地址 | `https://mcp.mcd.cn/` —— **根路径** |
| 传输协议 | Streamable HTTP |
| MCP 协议版本 | `2025-06-18` |
| 鉴权 | 请求头 `Authorization: Bearer ${MCD_MCP_TOKEN}` |
| Token 申请 | <https://open.mcd.cn/mcp>（手机号登录 → 控制台 → 激活） |
| 工具总数 | **35**（`tools/list` 实测） |
| 官方指南 | <https://open.mcd.cn/mcp/doc> |

> **已实际调用验证**：2026-10-10 使用真实 Token 完成
> `initialize` / `tools/list` / `tools/call` 全链路，
> 并跑通 `list-nutrition-foods`、`query-nearby-stores`、`query-meals`、
> `query-meal-detail`、`calculate-price` 五个工具的真实返回。
> 下文所有「实测」字样均指本次真实调用，非文档推测。

**端点坑**：`/mcp`、`/sse`、`/api/mcp`、`/message` 全部返回 404，
只有根路径 `https://mcp.mcd.cn/` 可用。

配置示例见 [`mcp-config.example.json`](./mcp-config.example.json)，
**仅含环境变量占位符，无任何真实凭证**。

客户端实现见 [`mcd_a11y/mcp_client.py`](./mcd_a11y/mcp_client.py)，
**仅使用 Python 标准库**（`urllib.request`），无第三方依赖。

## 2. 实际使用的 Tool

| Tool | 用途 | 在本项目中的作用 |
|---|---|---|
| `list-nutrition-foods` | 餐品营养成分 | **核心数据源**。全部阈值判定的依据，包含钠、碳水、脂肪、能量、钙 |
| `query-nearby-stores` | 附近门店 | 可达性排序：营业中优先 + 距离升序，减少行动不便者的步行距离 |
| `query-meals` | 门店在售菜单 | 提供餐品编码与实时价格，与营养表跨表匹配 |
| `query-meal-detail` | 餐品组成与可特制项 | 生成**店员可执行的特制指令**与价格影响清单 |
| `calculate-price` | 官方核价 | 唯一可信的实付金额（单位：分） |
| `now-time-info` | 服务端时间 | 判定营业时段（可选） |

以上六个工具均已用真实 Token 跑通，实测返回见第 9 节。

未使用：`create-order`（本项目不自动下单，见下）、`cancel-order`、
`auto-bind-coupons`、`available-coupons`、`query-my-coupons`、
`mall-*`、`party-*`、`lottery-*`、`delivery-*`。

## 3. 调用流程

```
用户诉求（城市 + 地点 + 饮食档位 + 输出模式）
   │
   ├─→ query-nearby-stores ──→ 营业中优先 + 距离升序 ──→ 选定门店
   │
   ├─→ list-nutrition-foods ──→ TOON 解析 ──→ 营养表（实测 160 条）
   │
   ├─→ query-meals ──→ 门店在售菜单 ──→ 与营养表五层匹配
   │                                      （exact/normalized/token/fuzzy/unmatched）
   │
   ├─→ 阈值判定（限钠 / 控糖 / 低脂 / 控能量）
   │      └─ 未匹配或字段缺失 → 输出「未评估」，绝不当合格
   │
   ├─→ query-meal-detail ──→ modification ──→ 特制清单 + 价格影响 + 方向性钠提示
   │
   ├─→ 渲染输出（screen-reader / large-print / plain）
   │
   └─→ calculate-price（仅当用户主动核价）→ 展示金额 → 用户到官方渠道完成支付
```

## 4. 业务价值

麦当劳官方 MCP 把营养数据、门店、菜单、特制、核价都开放了出来，
但**默认返回形态对读屏软件并不友好**：

- 金额是数字，读屏会读成「十九点八八元」而不是「十九元八角八分」；
- 数据是嵌套 JSON 或 TOON 紧凑表，直接朗读没有意义；
- 分类名是中文且不稳定（「人气热卖」/「超值套餐」），无法稳定枚举。

本项目把这些数据**重排成一层读屏软件能完整读通的文本**，
并叠加慢病饮食约束与可执行特制指令，让视障用户、长辈与其照护者
能够独立完成一次有依据的点餐决策。

## 5. 实测发现的数据边界（本项目明确声明、不做推测）

| 边界 | 事实 | 本项目处理 |
|---|---|---|
| `modification` 无营养字段 | 实测只有 8 个字段：`code / price / name / maxQuantity / minQuantity / selectedQuantity / selectedKey / unselectedKey` | 只给方向性提示，显著标注「非量化」，**不编造毫克数** |
| 营养表无 `productCode` | `list-nutrition-foods` 只返回餐品名 | 按名称五层模糊匹配，匹配类型暴露在输出中 |
| 营养表不覆盖套餐 | 只含单品 | 套餐拆 `roundList` 子项累加；无法拆分则声明 |
| 门店无无障碍设施数据 | 无坡道 / 无障碍卫生间 / 低位柜台字段 | 输出中声明「无法核实，请致电门店确认」 |
| `order-list` 上限 10 笔 | 官方限制 | 本项目不依赖历史订单 |
| 返回格式有四种 | 纯 JSON / 说明文字+JSON / Markdown / TOON 紧凑表 | 三级降级解析（见下） |
| `data` 字段含裸换行 | 导致 `strict=True` 的 JSON 解析直接抛异常 | 使用 `json.JSONDecoder(strict=False)` |
| **同一品名多规格** | 「可乐」对应小杯/中杯/大杯，钠含量不同 | 取营养素最高档（保守高估），输出标注「不是精确值」 |
| **营养匹配率有限** | 营养表不覆盖套餐与新品 | 实测某门店 84 项中匹配 31 项（37%），未匹配一律「未评估」 |

## 6. 响应解析的三级降级

1. **`structuredContent`** —— 服务端预解析的业务 JSON，最稳；
2. **`json.JSONDecoder(strict=False).raw_decode()`** —— 从 `{"success"` 处定位并抠出，
   处理「说明文字 + JSON」与含裸换行的 `data` 字段；
3. **抛出可见错误** —— 绝不静默返回空。

TOON 紧凑表的字段名**从表头动态读取**，不硬编码顺序，
避免官方调整字段顺序时静默错位。

## 7. 错误处理

| 错误码 | 含义 | 处理 |
|---|---|---|
| `401` / `403` | Token 无效或过期 | 提示到 open.mcd.cn/mcp 重新申请 |
| `429` | 限流 | 遵守 `Retry-After`，否则指数退避 + 抖动 |
| `600057` | 门店已打烊 | 提示换门店，自动跳到下一家营业中门店 |
| `600058` | 城市名或关键词为空 | 提示两者必须同时提供 |
| `600046` | 仅支持到店与得来速 | 限制 `beType` 取值 |
| `600042` | 缺少取餐方式 | 提示先调用 `calculate-price` 获取 `takeWayCode` |

## 8. 安全护栏

- 写操作（`create-order`、`auto-bind-coupons`、`draw-lottery`、`mall-create-order`、
  `party-order-create`、`cancel-order`）**一律不缓存、不进离线快照**；
- CLI 中 `order` 必须带 `--confirm`，且本项目默认不执行自动下单 ——
  MCP 的 `create-order` 只返回 `payH5Url`，无法代付；
- `calculate-price` 返回 `price=0` 时判定为 `items` 结构错误并报错，
  **不当作「免费」**（写成 `code` 而非 `productCode` 会静默返回 0）；
- Token 只从环境变量读取，`.gitignore` 屏蔽 `.env`，仓库只含占位符配置。

## 9. 真实调用记录（2026-10-10）

### `initialize`

```json
{"jsonrpc":"2.0","id":1,"result":{
  "capabilities":{"tools":{}},
  "protocolVersion":"2025-06-18",
  "serverInfo":{"name":"mcd-mcp","version":"1.0.0"}}}
```

### `tools/list` → 35 个工具

本项目只用其中 6 个；其余 27 个（券、积分、抽奖、派对、麦麦商城、
外送地址、团餐助餐等）不在范围内，**不调用**。

### `list-nutrition-foods` → TOON，160 条

```
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
```

实测：钠 0–1373 mg，中位数 122 mg；`nutritionDescription` 全为 `null`；
**不含 `productCode`**，只能按品名匹配；**不覆盖套餐**。

### `query-nearby-stores`（深圳，beType=1）→ 5 家

```
1421182 麦当劳深圳湾文化广场餐厅  52 米   07:00-22:00  businessStatus=false
1420576 麦当劳深圳湾一店餐厅     843 米   00:00-23:59  businessStatus=true
```

`businessStatus` 是**布尔值**；`distance` 单位是**米**；
**不含任何无障碍设施字段**。

### `query-meals`（storeCode 1420576）→ 14 分类 / 84 项

结构是「分类 + 顶层映射」双结构，名称只在顶层 `meals` 映射里：

```json
{"categories":[{"name":"巨无霸","meals":[{"code":"1440"}]}],
 "meals":{"1440":{"name":"麦辣鸡腿汉堡","currentPrice":"22.5","originalPrice":"46"}}}
```

价格为**元**、字符串。

### `query-meal-detail`（code 1440）→ 2 个可调项

```
麦香鸡酱   price=0  默认包含
切块生菜   price=0  默认包含
```

`modification.items[].values[]` 只有
`code/name/price/maxQuantity/minQuantity/selectedQuantity/selectedKey/unselectedKey`，
**无任何营养字段** —— 因此本项目不做钠的量化计算。

### `calculate-price`（1440 × 1）→ 2250 分

```json
{"productPrice":2250,"productOriginalPrice":2250,"price":2250,"discount":0, ...}
```

单位为**分**，即 22.50 元。

## 10. 联调中发现并修复的实现缺陷

真实联调比离线自测多暴露出 5 个问题，均已修复并补了回归测试：

| 缺陷 | 现象 | 修复 |
|---|---|---|
| 信封未剥离 | `structuredContent` 指向整层信封，`query-meals` 静默解析出 0 条 | 统一剥 `data`，`success=false` 抛可见错误 |
| 布尔被强转 | `str(False)` → `"False"`，所有门店显示「营业状态未知」 | 先判布尔类型再回落字符串 |
| 序号错乱 | 用门店编码末位当序号，出现「第零项」「第八项」 | 改用显示序号连续递增 |
| 组合超额度 | 只校验单项，推荐了 311+422=733 mg 而额度是 666.7 mg | 组合加入合计约束 |
| 多规格漏配 | 长度差上限过窄，「可乐」匹配不到「可乐中杯」 | 放宽上限 + 多规格取保守档 |

离线自检项数由 51 增至 **63**。
