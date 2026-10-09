# 🍔 麦麦读得到 · mcd-a11y-order

[![M-CODE 参赛作品](https://img.shields.io/badge/M--CODE-参赛作品-FFC72C?style=flat-square)](https://github.com/M-China/mcd-developer-innovation-challenge)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![零第三方依赖](https://img.shields.io/badge/依赖-仅标准库-2ea44f?style=flat-square)](https://github.com/)
[![tests](https://img.shields.io/badge/tests-51%20passed-brightgreen?style=flat-square)](./tests/test_offline.py)
[![MCP](https://img.shields.io/badge/MCP-mcp.mcd.cn-blueviolet?style=flat-square)](https://mcp.mcd.cn)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square)](./LICENSE)

> 麦当劳程序员创意开发大赛（M-CODE）参赛作品 · 非麦当劳官方产品 ·
> 数据全部来自官方 MCP 实时查询

**把麦当劳的营养表，变成读屏软件能完整读通的一句话。**

面向使用 NVDA / VoiceOver 的视障用户、长辈、认知障碍者及其照护者，
以及需要控制钠与糖的人群。

---

## 30 秒上手（不需要 Token）

```bash
git clone https://github.com/Lion-bot2026/mcd-a11y-order.git
cd mcd-a11y-order
python3 -m mcd_a11y demo --mode screen-reader
```

没有 `pip install`，没有配置文件，不需要账号。一条命令就能看到完整效果。

---

## 三种输出模式

同一份数据，三种读法。

### screen-reader（读屏友好）

```text
当前档位，限钠。日限额 2000 毫克，本餐额度 666.7 毫克（按三分之一折算，工程假设）。

这一餐可以选的餐食（钠由低到高）。
  第一项，大杯玉米杯。能量 87 千卡。钠 2 毫克。钠密度每百千卡 2 毫克。可以选
  第二项，迷你薯条。能量 106 千卡。钠 61 毫克。钠密度每百千卡 58 毫克。可以选
  第三项，小薯条。能量 210 千卡。钠 120 毫克。钠密度每百千卡 57 毫克。可以选

钠含量最高的几项（不建议）。
  第一项，培根安格斯厚牛堡。能量 707 千卡。钠 1037 毫克。超出本餐额度 370 毫克。不建议
  第二项，板烧鸡腿堡。能量 391 千卡。钠 1041 毫克。超出本餐额度 374 毫克。不建议
```

金额会读成「**十九元八角八分**」，而不是读屏软件默认的「十九点八八元」。

### large-print（大字极简）

一次只给 3 项，行间留白，不出现表格与符号。

### plain（普通 Markdown）

适合开发者调试与管道处理，另有 `--json` 可用。

---

## 和「只推荐」有什么不一样

| 维度 | 本项目的做法 |
|---|---|
| **读屏输出** | 中文货币读法、无表格、无符号、单位全中文、显式播报进度、编号连写（「第一项」而非「第 一 项」） |
| **慢病约束** | 限钠 / 控糖 / 低脂 / 控能量四档，每档标注权威口径与核实状态 |
| **可执行特制** | 输出店员能直接照做的改配清单，含每项对价格的影响 |
| **数据诚实** | 未获取到就说未获取，绝不当 0 通过；未匹配到就说未评估，既不当合格也不当不合格 |
| **不做量化编造** | MCP 的 `modification` 接口不返回分项营养数据，因此只给方向性提示，并显著标注 |
| **安全** | 不自动下单、不代付，写操作必须二次确认；核价返回 0 时判定为结构错误而非「免费」 |

---

## 实测发现（基于官方 MCP 真实返回的 156 条营养数据）

> 数据快照时间 2026-10-10，实际数值以官方 MCP 实时返回为准。

| 发现 | 数字 |
|---|---|
| 全部餐品 | 156 条，均含钠数据 |
| 其中主食类（非甜品饮品、能量 ≥ 60 千卡） | 100 条 |
| 在 WHO 限钠口径下（单餐 667 毫克）达标 | **63 条（63%）** |
| 汉堡类共 15 款，达标的 | **仅 2 款（汉堡包、儿童鱼排堡）—— 87% 超标** |
| 能量 380–560 千卡的 22 项餐品，钠含量跨度 | **258 → 1343 毫克，相差 5.2 倍** |

最后一行是本项目最想传达的一件事：**热量相近，不等于钠相近。**
同为 400 千卡左右的一餐，选错了钠可以是选对了的 5 倍。

---

## 无障碍设计说明

读屏模式遵守六条硬规则（实现见 [`mcd_a11y/render.py`](./mcd_a11y/render.py)）：

| 规则 | 为什么 |
|---|---|
| 金额读中文货币 | 读屏会把 `19.88元` 读成「十九点八八元」，不符合中文货币习惯 |
| 单位全中文 | `kcal` → 千卡、`mg` → 毫克，避免读屏逐字母拼读 |
| 禁用符号 | `★` `→` `≥` `×` 等会被读成莫名其妙的词，一律转文字 |
| 禁用表格 | 表格在 NVDA / VoiceOver 下会读出行列坐标，改用编号层级 |
| 禁用缩写 | SKU / BOM 等一律展开 |
| 显式进度 | 每步先报总数（「共 3 家」），让听者知道还要听多久 |

**已知能力边界（本项目明确声明，不做推测）**：
麦当劳 MCP 不返回门店无障碍设施信息（坡道、无障碍卫生间、低位柜台等），
因此本工具无法核实，每次输出门店时都会提示「请到店前致电门店确认」。

---

## 慢病档位与阈值溯源

| 档位 | 阈值 | 权威口径 | 溯源 | 已核实 |
|---|---|---|---|:---:|
| 限钠 | 2000 毫克/日 | 成人每日钠摄入低于 2000 毫克（约合食盐 5 克） | WHO《Sodium intake for adults and children》(2012) | ✅ |
| 控糖 | 游离糖供能 < 10% | 由能量目标推导：克数 = 能量 × 10% ÷ 4 | WHO《Guideline: sugars intake for adults and children》(2015) | ✅ |
| 低脂 | 脂肪供能比 20%–30% | 由能量目标推导 | 《中国居民膳食指南（2022）》 | ⚠️ 待核实 |
| 控能量 | 使用者自填 | 无外部权威口径 | — | ✅ |

**两条必须说清楚的边界：**

1. **单餐额度 = 日限额 × 三分之一，这是工程假设，不是权威标准。**
   每次输出都会标注这一点，可用 `--sodium-cap` 覆盖。
2. **控糖档位用的是「总碳水化合物」代理指标。**
   MCP 只提供碳水化合物总量、不区分游离糖。总碳水 ≥ 游离糖，
   所以判定**偏严格（保守）**，不会漏放过线餐品 —— 但这不等于精确计算游离糖。

**主动放弃的能力**：本项目**不提供「低蛋白」档位**。
慢性肾脏病的蛋白质摄入需按体重与分期个体化确定（g/kg/d），
给一个固定克数存在误导肾病患者的风险。

---

## 数据边界声明（本项目最重要的一节）

`query-meal-detail` 的 `modification` 字段实测只返回 8 个字段：

```json
{"code":"100202","price":0,"name":"酸黄瓜","maxQuantity":1,"minQuantity":0,
 "selectedQuantity":1,"selectedKey":"0-1","unselectedKey":"0-0"}
```

**没有任何营养字段。**

因此本项目对「特制」只输出三件事，且第三件会显著标注：

1. 可特制项清单 —— 真实数据
2. 每项对**价格**的影响 —— 真实数据
3. 对钠的**方向性提示**（如「酱料通常是钠的主要来源」）—— 规则库推断，
   同时输出「麦当劳 MCP 不提供分项营养数据，本项目不做钠的量化计算」

**本项目不会输出「去掉酱料可减少 620 毫克钠」这类数字**，因为官方接口没有这个数据。

其他已确认并规避的边界：

- 营养表**不含 `productCode`**，只能按名称匹配 → 五层降级匹配，匹配类型暴露在输出中
- 营养表**不覆盖套餐** → 拆子项累加，无法拆分则声明
- `order-list` **硬上限 10 笔** → 本项目不依赖历史订单
- 响应格式有 4 种（纯 JSON / 说明文字+JSON / Markdown / TOON）→ 三级降级解析
- `data` 字段含裸换行 → 必须用 `strict=False` 解析，否则直接抛异常

---

## 接入真实 MCP

```bash
# 1. 申请 Token：https://open.mcd.cn/mcp
#    手机号登录 → 右上角「控制台」→「激活」→ 复制

# 2. 注入环境变量（不要写进代码，不要提交到仓库）
export MCD_MCP_TOKEN=你的Token

# 3. 使用
python3 -m mcd_a11y stores --city 上海 --keyword 徐汇
python3 -m mcd_a11y plan  --city 上海 --keyword 徐汇 --profile sodium --mode screen-reader
python3 -m mcd_a11y tweak  --store <门店编码> --code <餐品编码>
python3 -m mcd_a11y quote  --store <门店编码> --items '[{"productCode":"xxx","quantity":1}]'
```

Token 只从环境变量读取。`.gitignore` 屏蔽 `.env`，仓库只含 `${MCD_MCP_TOKEN}` 占位符。

---

## 命令一览

| 命令 | 作用 | 需要 Token |
|---|---|:---:|
| `demo` | 离线演示，一条命令出效果 | ❌ |
| `profiles` | 列出档位与阈值溯源 | ❌ |
| `stores` | 门店（营业中优先 + 距离升序） | ✅ |
| `plan` | 主命令：按档位筛选这一餐能吃什么 | ✅ |
| `tweak` | 特制清单（价格影响 + 方向性钠提示） | ✅ |
| `quote` | 官方核价（金额单位：分） | ✅ |
| `order` | 下单（必须 `--confirm`，且默认不执行自动下单） | ✅ |

---

## 目录结构

```
mcd-a11y-order/
├── CONTEST_DECLARATION.md      # 参赛声明（官方原文，未修改）
├── MCP_INTEGRATION.md          # MCP 接入说明
├── SKILL.md                    # WorkBuddy / Agent Skill 定义
├── mcp-config.example.json     # 脱敏配置（仅占位符）
├── mcd_a11y/
│   ├── mcp_client.py           # 零依赖 Streamable HTTP 客户端
│   ├── parser.py               # 四种响应格式解析 + TOON 解析
│   ├── nutrition.py            # 营养模型、五层匹配、阈值判定
│   ├── profiles.py             # 慢病档位与溯源
│   ├── menu.py                 # 门店、菜单、特制
│   ├── render.py               # 三种输出模式 + 中文货币读法
│   ├── demo_data.py            # 离线演示数据
│   └── cli.py                  # 命令行入口
├── tests/test_offline.py       # 51 项离线自检
└── data/nutrition_snapshot.json
```

## 测试

```bash
python3 -m unittest discover tests -v
```

51 项离线自检，不需要 Token、不需要网络。重点覆盖：
缺失值不当 0、未匹配不当合格、TOON 字段名动态读取、
中文货币读法、编号连写、写操作不缓存、特制无营养字段。

---

## 安全与合规

- **不自动下单。** MCP 的 `create-order` 只返回支付链接，无法代付；
  本项目 CLI 中 `order` 必须带 `--confirm`，且默认不执行。
- **核价返回 0 判定为错误。** `items` 字段名写成 `code` 而非 `productCode`
  不会报错、只会静默返回 `price=0`。本项目强制只用 `productCode`，
  并对返回 0 报错，绝不当作「免费」。
- **写操作不缓存。** `create-order` / `auto-bind-coupons` 等一律绕过缓存。
- **无真实凭证。** 仓库只含环境变量占位符，`.gitignore` 屏蔽 `.env`。
- **描述用户用尊重性表述**，不给视障或老年用户贴标签。

## 免责声明

本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，
**非麦当劳官方产品**。

**项目输出仅供参考，不构成医疗、营养或其他专业建议。**
餐品信息、营养成分、价格及供应状态以麦当劳官方渠道的实时结果为准。
有特定疾病或营养需求者，请咨询医师或临床营养师。

---

MIT License
