# WorkBuddy 开发上下文

本文件记录 `mcd-a11y-order`（麦麦读得到 · 麦当劳无障碍点餐助手）在
**腾讯 WorkBuddy** 中的真实开发过程，用于核验 WorkBuddy 专项奖励条件。

- **开发平台**：腾讯 WorkBuddy（https://www.workbuddy.cn）
- **开发方式**：在 WorkBuddy 会话中通过自然语言指令驱动，由 WorkBuddy 完成
  资料检索、竞品调研、方案设计、代码编写、测试与文档产出。
- **开发时间**：2026-10-09 至 2026-10-10
- **项目目录**：`/Users/ares/AresEvolution/人工智能（AI）/E_实践案例/麦当劳/mcd-a11y-order`

---

## 一、需求提出

> Workbuddy 和麦当劳发起了一个程序员创意开发大赛，我想和你一起参赛。
> 你先阅读一下活动介绍和规则，然后我们再进一步沟通。
> 目标是进入 100 强，并力争拿奖。
> 活动介绍：https://waytoagi.feishu.cn/wiki/XC3xwq0PSi5l2ckSElqcDVZAn9d ，
> https://builderx.csdn.net/activity-site/m-code/pages

## 二、规则调研结论

WorkBuddy 读取了官方仓库 `M-China/mcd-developer-innovation-challenge` 的
`README.md`、`activityGuidelines.md`、`CONTEST_DECLARATION.md`、`RANKING.md`，
确认关键规则：

- 排名**只按 GitHub 公开 Star 数**排序，前 100 名进榜拿奖，Star=0 不进榜；
- 定榜时间 2026-10-26 00:00（北京时间）；
- 同一 GitHub 账号只有 Star 最高的项目进榜；
- 必须交付 `README.md`、`CONTEST_DECLARATION.md`（内容不可改）、
  `MCP_INTEGRATION.md`、`mcp-config.example.json`、源代码；
- 提交 `workbuddy.md` 可参与 WorkBuddy 专项奖励（前 100 名 3000 积分）。

CSDN 活动页为纯图片落地页，WorkBuddy 通过解析其 HTML 源码定位到官方 GitHub 仓库链接。

## 三、竞品调研（决定方向的关键一步）

WorkBuddy 逐条核查了 155 条报名 Issue，发现最初设想的「无障碍」方向并非完全空白：

| 项目 | Star | 覆盖 |
|---|---:|---|
| `mcd-easy-order`（麦麦轻松点） | 5 | 大字菜单、Web UI、屏幕阅读器 ARIA 标签、可打印沟通卡、离线演示 |
| `mcd-diet-guard`（膳食守门员） | 0 | 8 类人群画像阈值判定、声称「量化改配」 |
| `mcd-no-pickle` | 2 | 去酸瓜特制 |

关键发现是**三者交集为空**：

- `mcd-easy-order` 的 `MCP_INTEGRATION.md` 明写「读取 `isDefault=1` 的默认组合」，
  **主动放弃了改配**；
- `mcd-diet-guard` **没有无障碍输出层**。

因此方向收窄为：**读屏优先的纯文本输出层 × 慢病约束 × 可执行特制指令**。

## 四、一项关键的能力降级（重要）

WorkBuddy 拉取了 `mcd-no-pickle` 的真实抓包，确认
`query-meal-detail` 的 `modification.items[].values[]` 只有 8 个字段：

```json
{"code":"100202","price":0,"name":"酸黄瓜","maxQuantity":1,"minQuantity":0,
 "selectedQuantity":1,"selectedKey":"0-1","unselectedKey":"0-0"}
```

**没有任何营养字段。** 同时交叉核对 `mcd-diet-guard` 的营养快照，
检索「酱」「酸瓜」均为 0 命中 —— 其宣称的「去酱料钠 -620mg」
是手工填入的示例、不是 MCP 返回数据。

结论：原定的「量化减钠特制」**不可实现**，降级为
「选项清单 + 价格影响 + 方向性钠提示（显著标注非量化）」。
本项目**不编造任何毫克数**。

## 五、开发过程中的实测修正

以下问题是 WorkBuddy 在开发中实测发现并修正的：

1. **`json.JSONDecoder` 必须 `strict=False`** —— `data` 字段含裸换行，
   `strict=True` 会直接抛异常。
2. **纯按钠排序会把可乐顶到第一位** —— 可乐钠 0 毫克，但对「这一餐吃什么」
   毫无帮助。增加甜品/饮品识别，分区展示。
3. **「第 一 项」会被读屏逐字读出** —— 改为连写「第一项」。
4. **「限钠 0 毫克」读不通** —— 档位名称与数值名称分离，输出「钠 0 毫克」。
5. **`--mode` 参数位置** —— 改为挂在子命令上，前后都能用。
6. **dataclass 字段顺序** —— 有默认值的字段不能排在无默认值字段之前。

## 六、最终交付

| 文件 | 说明 |
|---|---|
| `README.md` | 项目介绍、上手、实测输出、阈值溯源、数据边界、免责声明 |
| `CONTEST_DECLARATION.md` | 参赛声明（**官方原文，未修改**） |
| `MCP_INTEGRATION.md` | MCP Server / Tool / 调用流程 / 业务价值 / 数据边界 |
| `mcp-config.example.json` | 脱敏配置，仅 `${MCD_MCP_TOKEN}` 占位符 |
| `SKILL.md` | WorkBuddy / Agent Skill 定义，含六条无障碍输出规则 |
| `mcd_a11y/` | 零第三方依赖源码（仅 Python 标准库） |
| `tests/test_offline.py` | 51 项离线自检，全部通过 |
| `data/nutrition_snapshot.json` | 156 条真实营养快照（来自 `list-nutrition-foods`） |

## 七、实测数据（用于 README 与传播）

基于官方 MCP 真实返回的 156 条营养数据：

- 主食类（非甜品饮品、能量 ≥ 60 千卡）100 条；
- 在 WHO 限钠口径下（单餐 667 毫克）达标 63 条（63%）；
- 汉堡类 15 款，仅 2 款达标 —— **87% 超标**；
- 能量 380–560 千卡的 22 项，钠 258 → 1343 毫克，**相差 5.2 倍**。

## 八、WorkBuddy 在本项目中的具体作用

1. 读取并比对官方活动规则、榜单与 155 条报名 Issue，完成竞品定位；
2. 拉取社区项目源码，核实 MCP 真实能力与数据边界（避免了编造营养数据）；
3. 设计方案并完成全部代码实现（零依赖 MCP 客户端、TOON 解析、五层匹配、
   三种输出模式、中文货币读法）；
4. 编写 51 项离线自检并全部通过；
5. 产出 README、MCP_INTEGRATION、SKILL 等全部交付文档。
