# -*- coding: utf-8 -*-
"""文档一致性 —— 从快照现场计算，与文档比对。

防的是「同一份交付物里出现两个数字」：这个项目把数据可溯源当红线，
如果 README 说160 条营养、workbuddy.md 说 156 条，读者会连带怀疑
其余所有数据的可靠性 —— 代价比想象的更大。

设计要点：
1. 数字只有一个来源：data/nutrition_snapshot.json。测试现场算，文档写错就红。
2. 只锁「能从快照算出」的数（条数/达标数/汉堡数），不锁「测试数量」——
   加一条测试就会让写死的数量立刻过期，那是条会自我破坏的断言。
3. 不引入第三方依赖。
"""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 与 profiles.MEAL_SHARE_DEFAULT / WHO 口径保持一致：
# 日限额 2000 mg，单餐按三分之一折算
NUTRIENT_LIMIT = round(2000 / 3, 1)
MIN_KCAL = 60


def _load():
    path = os.path.join(ROOT, "data", "nutrition_snapshot.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read(name):
    return open(os.path.join(ROOT, name), encoding="utf-8").read()


def _facts():
    """从快照现场计算关键统计量。"""
    import sys
    sys.path.insert(0, ROOT)
    from mcd_a11y.menu import is_light_food

    foods = _load()["foods"]
    # 「主食类」口径：非甜品饮品（按名称识别）且能量 >= 60 kcal
    staple = [f for f in foods
              if not is_light_food(f["productName"])
              and (f.get("energyKcal") or 0) >= MIN_KCAL]
    ok = [f for f in staple
          if f.get("sodium") is not None and f["sodium"] <= NUTRIENT_LIMIT]
    burgers = [f for f in foods if "堡" in f["productName"]]
    burgers_ok = [f for f in burgers
                  if f.get("sodium") is not None and f["sodium"] <= NUTRIENT_LIMIT]
    return {
        "total": len(foods),
        "staple": len(staple),
        "staple_ok": len(ok),
        "staple_pct": round(len(ok) / len(staple) * 100) if staple else 0,
        "burger_total": len(burgers),
        "burger_ok": len(burgers_ok),
        "burger_pct": round((1 - len(burgers_ok) / len(burgers)) * 100)
        if burgers else 0,
    }


class TestSnapshotIntegrity(unittest.TestCase):
    """先固定「事实本身」—— 快照变了必须是有意为之。"""

    def test_count_matches_meta(self):
        d = _load()
        self.assertEqual(len(d["foods"]), d["_meta"]["count"])

    def test_no_credentials_in_snapshot(self):
        """快照绝不能含Token 或手机号等个人信息。"""
        raw = _read("data/nutrition_snapshot.json")
        self.assertNotRegex(raw, r"[A-Za-z0-9]{28,40}")
        self.assertNotIn("1iSdDwxY", raw)


class TestDocsMatchSnapshot(unittest.TestCase):
    """M10 防复发：文档里的关键数字必须与快照一致。"""

    def test_readme_uses_correct_counts(self):
        f = _facts()
        readme = _read("README.md")
        self.assertIn(f"{f['total']} 条", readme)
        self.assertIn(f"{f['staple']} 条", readme)
        self.assertIn(f"{f['staple_ok']} 条", readme)

    def test_readme_burger_facts(self):
        f = _facts()
        readme = _read("README.md")
        self.assertIn(str(f["burger_total"]), readme)
        self.assertIn(str(f["burger_ok"]), readme)

    def test_no_stale_numbers(self):
        """过期数字 156 / 100 条 / 63 条(63%) 不得残留在任何交付物里。"""
        stale = {
            "156": "旧版社区快照的条数（官方实时是 160）",
            "主食类（非甜品饮品、能量 ≥ 60 千卡）100": "旧版主食类计数（现为 97）",
        }
        targets = ("README.md", "workbuddy.md", "SKILL.md",
                   "MCP_INTEGRATION.md", "references/thresholds.md",
                   "references/mcp-tools.md", "references/output-rules.md",
                   "mcd_a11y/demo_data.py")
        offenders = []
        for fn in targets:
            for i, line in enumerate(_read(fn).splitlines(), 1):
                for bad, why in stale.items():
                    if bad in line:
                        # references/mcp-tools.md 里那句是「不是社区流传的 156 条」，
                        # 属于刻意的对比说明，保留。
                        if fn == "references/mcp-tools.md" and "不是" in line:
                            continue
                        offenders.append(f"{fn}:{i} 含过期数字 {bad!r}（{why}）：{line.strip()[:60]}")
        self.assertEqual(offenders, [], "\n".join(offenders))


class TestNoPhantomCapabilities(unittest.TestCase):
    """文档不得承诺代码里不存在的能力 —— 这项目把诚实当红线。"""

    def test_no_combo_accumulation_claim(self):
        """套餐拆 roundList 子项累加从未实现（mcd_a11y 下零命中）。"""
        offenders = []
        for fn in ("README.md", "MCP_INTEGRATION.md", "SKILL.md",
                   "references/thresholds.md", "references/mcp-tools.md",
                   "workbuddy.md"):
            for i, line in enumerate(_read(fn).splitlines(), 1):
                if "roundList" in line or ("套餐" in line and "累加" in line
                                           and "不做" not in line):
                    offenders.append(f"{fn}:{i} {line.strip()[:70]}")
        self.assertEqual(offenders, [],
                         "套餐累加的承诺已复活：\n" + "\n".join(offenders))

    def test_combo_accumulation_really_absent(self):
        """反向确认：代码里确实没有这个能力（若将来实现了，本测试需更新）。"""
        import subprocess
        hit = subprocess.run(
            ["grep", "-rn", "roundList", os.path.join(ROOT, "mcd_a11y")],
            capture_output=True, text=True)
        self.assertEqual(hit.stdout.strip(), "",
                         "代码里出现了 roundList，请更新文档口径")

    def test_cache_claim_is_factual(self):
        """客户端没有缓存层，文档不能承诺「写操作不缓存」这种空头承诺。"""
        for fn in ("README.md", "workbuddy.md"):
            text = _read(fn)
            self.assertNotIn("写操作不缓存", text,
                             f"{fn} 仍写着没有缓存层支撑的空承诺")

    def test_json_claim_matches_reality(self):
        """--json 只在 profiles 上真实存在。"""
        import subprocess
        cli = open(os.path.join(ROOT, "mcd_a11y", "cli.py"),
                   encoding="utf-8").read()
        self.assertEqual(cli.count('"--json"'), 1,
                         "只有 profiles 保留 --json，出现数量变化需同步文档")
        readme = _read("README.md")
        self.assertIn("`profiles` 另有 `--json`", readme,
                      "README 需说明 --json 仅 profiles 可用")


class TestHardRuleCount(unittest.TestCase):
    """「六条硬规则」实际列举了 7 条 —— 统一为七条。"""

    def test_no_six_claims(self):
        offenders = []
        for fn in ("README.md", "SKILL.md", "workbuddy.md",
                   "references/output-rules.md"):
            for i, line in enumerate(_read(fn).splitlines(), 1):
                if "六条" in line:
                    offenders.append(f"{fn}:{i} {line.strip()[:60]}")
        self.assertEqual(offenders, [], "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()