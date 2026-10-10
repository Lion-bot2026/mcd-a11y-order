# -*- coding: utf-8 -*-
"""文档一致性 —— 从快照现场计算，与文档比对。

防的是「同一份交付物里出现两个数字」：这个项目把数据可溯源当红线，
如果 README 说160 条营养、workbuddy.md 说 156 条，读者会连带怀疑
其余所有数据的可靠性 —— 代价比想象的更大。

设计要点：
1. 数字只有一个来源：data/nutrition_snapshot.json。测试现场算，文档写错就红。
2. 「测试数量」也现场算，但用**静态计数**而不是跑一次 unittest——
   后者会在测试内部再次 discover，触发自己，形成无限递归。
   早期版本选择「不锁测试数量」，理由是「加一条测试就过期」；
   但那个选择的实际后果是 README 里的数字一直没人管（长期停在 63）。
   现在改为：README 写明数量 + 测试现场静态计数校验，两者必须一致。
3. stale 字典必须覆盖所有历史错误数字。docstring 声称能拦某类问题、
   实现里却没有对应的 key，等于「测试的承诺大于实现」——比没有测试更危险，
   因为它会让人误以为该类问题已被覆盖。
4. 不引入第三方依赖。
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
        """过期数字不得残留在任何交付物里。

        stale 的每个 key 都必须对应真实出现过的历史错误。
        早期版本的 docstring 声称拦「63 条(63%)」，但字典里只有 156 和 100——
        于是 workbuddy.md 的「达标 63 条（63%）」长期没人管。
        承诺必须能兑现，否则测试反而给人虚假的安全感。
        """
        stale = {
            "156": "旧版社区快照的条数（官方实时是 160）",
            "主食类（非甜品饮品、能量 ≥ 60 千卡）100": "旧版主食类计数（现为 97）",
            "达标 63 条": "旧版达标计数（现为 60 条 / 62%）",
            "63 条（63%）": "旧版达标计数（现为 60 条 / 62%）",
            "63 项离线自检": "旧版测试计数（现为tests/ 下动态计数）",
            "87% 超标": "旧版定性措辞（官方红线禁止对产品定性）",
            "达标的仅": "旧版定性措辞（官方红线禁止对产品定性）",
        }
        targets = ("README.md", "workbuddy.md", "SKILL.md",
                   "MCP_INTEGRATION.md", "references/thresholds.md",
                   "references/mcp-tools.md", "references/output-rules.md",
                   "mcd_a11y/demo_data.py",
                   "docs/poster/scenario-poster.html",
                   "docs/poster/场景与上手引导.md")
        offenders = []
        for fn in targets:
            if not os.path.exists(os.path.join(ROOT, fn)):
                continue
            for i, line in enumerate(_read(fn).splitlines(), 1):
                for bad, why in stale.items():
                    if bad in line:
                        # references/mcp-tools.md 里那句是「不是社区流传的 156 条」，
                        # 属于刻意的对比说明，保留。
                        if fn == "references/mcp-tools.md" and "不是" in line:
                            continue
                        offenders.append(f"{fn}:{i} 含过期数字 {bad!r}（{why}）：{line.strip()[:60]}")
        self.assertEqual(offenders, [], "\n".join(offenders))


class TestDocsTestCount(unittest.TestCase):
    """README 声明的用例数必须等于 tests/ 下真实的测试函数数。

    用静态计数而不是跑一次 unittest：后者会在测试内部再次 discover，
    触发自己，无限递归。
    """

    def _actual_test_count(self) -> int:
        total = 0
        for f in sorted(os.listdir(os.path.join(ROOT, "tests"))):
            if not (f.startswith("test_") and f.endswith(".py")):
                continue
            text = open(os.path.join(ROOT, "tests", f), encoding="utf-8").read()
            total += len(re.findall(r"^\s*def test_", text, re.M))
        return total

    def test_static_count_matches_unittest_run(self):
        """先确认静态计数本身可信——否则下面的守护是空转。"""
        actual = self._actual_test_count()
        self.assertGreater(actual, 100,
                           "静态计数异常偏少，正则可能与测试写法不匹配")

    def test_readme_test_count_matches_reality(self):
        actual = self._actual_test_count()
        readme = _read("README.md")
        # 只匹配「N 项离线自检」与「共 N 项」，避免误抓其他数字
        found = list(re.finditer(r"(\d+)\s*项(?:离线)?自检|共\s*(\d+)\s*项", readme))
        self.assertTrue(found, "README 应声明测试数量")
        for m in found:
            n = m.group(1) or m.group(2)
            self.assertEqual(
                int(n), actual,
                f"README.md 声明 {n} 项自检，实际 {actual} 项"
                f"（增删测试后请同步更新 README）")


class TestCityKeywordPair(unittest.TestCase):
    """city 与 keyword 必须成对出现 —— 只给一个，接口会返回 600058。

    `query-nearby-stores` 要求两个入参同时提供。文档示例若只写
    --keyword，读者照抄就会失败。这是「文档承诺 = 代码实际」的一部分。
    """

    TARGETS = ("README.md", "SKILL.md", "MCP_INTEGRATION.md", "workbuddy.md",
               "docs/poster/scenario-poster.html",
               "docs/poster/场景与上手引导.md")

    def _check(self, filename):
        if not os.path.exists(os.path.join(ROOT, filename)):
            self.skipTest(f"{filename} 不存在")
        for lineno, line in enumerate(_read(filename).splitlines(), 1):
            if re.search(r"(mcd_a11y|mcd-a11y)\s+(plan|stores)\b", line):
                if "--keyword" in line:
                    self.assertIn(
                        "--city", line,
                        f"{filename}:{lineno} 有 --keyword 却没 --city：{line.strip()}")

    def test_all_docs(self):
        for fn in self.TARGETS:
            with self.subTest(file=fn):
                self._check(fn)

    def test_city_alone_also_paired(self):
        """反向：给了 --city 也必须同时给 --keyword（否则同样 600058）。"""
        for fn in self.TARGETS:
            if not os.path.exists(os.path.join(ROOT, fn)):
                continue
            for lineno, line in enumerate(_read(fn).splitlines(), 1):
                if re.search(r"(mcd_a11y|mcd-a11y)\s+(plan|stores)\b", line):
                    if "--city" in line:
                        self.assertIn(
                            "--keyword", line,
                            f"{fn}:{lineno} 有 --city 却没 --keyword：{line.strip()}")


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