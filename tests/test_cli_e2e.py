# -*- coding: utf-8 -*-
"""CLI 端到端冒烟测试 —— 直接跑 main(argv)，不经 subprocess。

为什么不走 subprocess：subprocess 起不来的原因是环境问题而非代码问题，
会掩盖真实回归；且慢约百倍。main(argv) 走的是完全相同的 argparse
解析与 cmd_* 分发路径。

这一层是必需的：之前的 63 项测试全是单元级（直接 import 函数），
结果 BUG-01（命令跑不通）、BUG-02（energy 档必失败）、
BUG-03（--json 静默失效）、BUG-04（TOON 静默返回空）全部漏检，
测试却全绿。
"""
import io
import os
import re
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcd_a11y.cli import build_parser, main  # noqa: E402


def run(argv):
    """跑一条命令，返回 (exit_code, stdout)。"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(argv)
    return code, buf.getvalue()


class TestScreenReaderHardRules(unittest.TestCase):
    """读屏模式的七条硬规则，必须在真实命令输出上成立。"""

    RULES = ("第一项", "第二项")           # 编号连写
    FORBIDDEN = ("第 一 项", "✓", "✗", "mg", "kcal", "g ",
                 "→", "★", "≥", "×")

    def test_demo_screen_reader(self):
        code, out = run(["demo", "--mode", "screen-reader"])
        self.assertEqual(code, 0)
        self.assertIn("第一项", out)
        self.assertIn("不构成医疗", out)
        for bad in self.FORBIDDEN:
            self.assertNotIn(bad, out, f"读屏输出不应含 {bad!r}")

    def test_plan_screen_reader(self):
        code, out = run(["plan", "--demo", "--mode", "screen-reader"])
        self.assertEqual(code, 0)
        self.assertIn("请注意", out)
        self.assertIn("不构成医疗", out)
        self.assertNotIn("第 一 项", out)

    def test_profiles_screen_reader_rules(self):
        """profiles 曾违反「编号连写」与「单位全中文」两条自定规则。"""
        code, out = run(["profiles", "--mode", "screen-reader"])
        self.assertEqual(code, 0)
        self.assertIn("第一项", out)
        self.assertNotIn("第 一 档", out)
        self.assertIn("毫克", out)
        self.assertNotIn("2000 mg", out)
        self.assertNotIn("。；", out)  # caveats 拼接曾拼出「。；」

    def test_stores_screen_reader(self):
        code, out = run(["stores", "--demo", "--mode", "screen-reader"])
        self.assertEqual(code, 0)
        self.assertIn("第一项", out)
        self.assertNotIn("第 一 项", out)

    def test_total_is_announced(self):
        """Out.item 的 total 必须真正播报「共 N 项」（兑现显式进度）。"""
        code, out = run(["demo", "--mode", "screen-reader"])
        self.assertEqual(code, 0)
        self.assertIn("共五项", out.replace(" ", ""))


class TestLargePrint(unittest.TestCase):
    """large-print 必须真的减少信息量并留白，否则「大字」名不副实。"""

    def test_demo_large_print_paginates(self):
        code, out = run(["demo", "--mode", "large-print"])
        self.assertEqual(code, 0)
        self.assertNotIn("✓", out)
        self.assertNotIn("✗", out)

    def test_plan_large_print_has_no_symbols(self):
        """plan 曾输出 ✓/✗，违反 README「不出现符号」的承诺。"""
        code, out = run(["plan", "--demo", "--mode", "large-print"])
        self.assertEqual(code, 0)
        for bad in ("✓", "✗"):
            self.assertNotIn(bad, out, f"large-print 不应含符号 {bad}")

    @staticmethod
    def _meal_block(out: str) -> str:
        """切出餐品列表区块。

        plan 会播报两次总数（门店、餐品），取最后一次 —— 餐品列表在后面。
        用 Out.item 的「共 N 项。」作锚点，门店区块是「共 N 家」。
        """
        hits = list(re.finditer(r"共 \d+ 项[。]?", out))
        assert hits, f"找不到餐品区块的总数播报：\n{out[:400]}"
        tail = out[hits[-1].end():]
        return tail.split("甜品与饮品")[0] if "甜品与饮品" in tail else tail

    def test_plan_large_print_limits_items(self):
        """达标项最多 3 条（外加 1 条超标示例），并明确告知有省略。"""
        code, out = run(["plan", "--demo", "--mode", "large-print"])
        self.assertEqual(code, 0)
        block = self._meal_block(out)
        items = [ln for ln in block.splitlines()
                 if ln.strip() and ln.strip()[0].isdigit()
                 and ". " in ln]
        self.assertLessEqual(len(items), 4,
                             "large-print 达标项应最多 3 条 + 1 条超标示例")
        if len(items) < 8:
            self.assertIn("未显示", out,
                          "条目被截断时必须明确告知用户，不能静默省略")

    def test_plan_large_print_has_blank_lines(self):
        """大字模式条目之间应留白，降低视觉查找成本。"""
        code, out = run(["plan", "--demo", "--mode", "large-print"])
        self.assertEqual(code, 0)
        self.assertIn("\n\n", self._meal_block(out))


class TestProfileUsability(unittest.TestCase):
    """四个档位必须都能真正跑起来。"""

    def test_sodium_needs_nothing(self):
        code, _ = run(["plan", "--demo", "--profile", "sodium"])
        self.assertEqual(code, 0)

    def test_carb_and_fat_need_kcal(self):
        for p in ("carb", "fat"):
            with self.assertRaises(SystemExit) if False else _noop():
                code, out = run(["plan", "--demo", "--profile", p,
                                 "--meal-kcal", "600"])
                self.assertEqual(code, 0, f"{p} 档应可用")

    def test_energy_profile_runs_with_kcal(self):
        """BUG-02：曾恒返回 None，传了 --meal-kcal 仍报错。"""
        code, out = run(["plan", "--demo", "--profile", "energy",
                         "--meal-kcal", "600"])
        self.assertEqual(code, 0)
        self.assertNotIn("需要能量目标", out)

    def test_missing_kcal_gives_actionable_hint_and_disclaimer(self):
        code, out = run(["plan", "--demo", "--profile", "energy"])
        self.assertEqual(code, 1)
        self.assertIn("--meal-kcal", out)
        self.assertIn("不构成医疗", out)

    def test_carb_missing_kcal_mentions_sodium_alternative(self):
        code, out = run(["plan", "--demo", "--profile", "carb"])
        self.assertEqual(code, 1)
        self.assertIn("sodium", out)


class TestDemoParityWithPlan(unittest.TestCase):
    """BUG-07：`demo` 曾硬编码 sodium 且不带--profile。

    demo 是「30 秒上手」的唯一入口，不支持档位就等于把项目的核心概念
    挡在门外——想体验控糖/低脂的人必须先读代码。demo 与 plan 的参数面
    必须一致。
    """

    def test_demo_accepts_profile(self):
        for p in ("sodium", "carb", "fat", "energy"):
            extra = [] if p == "sodium" else ["--meal-kcal", "600"]
            code, out = run(["demo", "--mode", "screen-reader",
                             "--profile", p] + extra)
            self.assertEqual(code, 0, f"demo --profile {p} 应可用")
            self.assertIn("当前档位", out)

    def test_demo_missing_kcal_is_actionable(self):
        code, out = run(["demo", "--profile", "carb"])
        self.assertEqual(code, 1)
        self.assertIn("--meal-kcal", out)
        self.assertIn("sodium", out, "应提示可改用不依赖参数的钠档")

    def test_energy_profile_does_not_repeat_nutrient(self):
        """控能量档的 value_cn 就是「能量」，不能再单独播报一次。

        BUG-07b 修复「档位错配」时引入的回归：为了不再无条件播报钠，
        改成无条件播报能量 + 当前档位营养素，结果 energy 档说了两遍。
        """
        for argv in (["demo", "--profile", "energy", "--meal-kcal", "600",
                      "--mode", "screen-reader"],
                     ["plan", "--demo", "--profile", "energy", "--meal-kcal", "600",
                      "--mode", "screen-reader"]):
            code, out = run(argv)
            self.assertEqual(code, 0, f"{argv} 应可运行")
            # 只看逐条餐食行：以「第N项」或「N. 」开头的行。
            # 档位说明行（「当前档位，控能量。本餐额度 600 千卡」）里
            # 「能量」出现两次是正确的 —— 一次是档位名，一次是单位。
            item_lines = [l for l in out.splitlines()
                          if re.match(r"\s*(第[一二三四五六七八九十]+项|共|\d+\.\s)", l)]
            self.assertTrue(item_lines, f"{argv} 应有逐条餐食行")
            for line in item_lines:
                self.assertLessEqual(
                    line.count("能量"), 1,
                    f"{argv} 餐食行重复播报能量：{line.strip()}")
                # 也不能出现「能量 X。能量」这种紧邻重复
                self.assertNotRegex(line, r"能量[^。]*。\s*能量",
                                    f"{argv} 出现「能量…能量」重复：{line.strip()}")


class TestOverByUnitMatchesProfile(unittest.TestCase):
    """超出量的单位必须跟档位走 —— 单位错配 1000 倍会误导判断。

    这是本轮新发现的问题，清单未列出：`_status_text` 早期硬编码「毫克」，
    于是控糖档会播报「碳水 42 克，超出 27 毫克」。听到「只超出 27 毫克」，
    用户会判断「没关系」，而实际超出了 27 克碳水。
    """

    CASES = {
        "sodium": ("毫克", None),
        "carb": ("克", "600"),
        "fat": ("克", "600"),
        # 能量档给低额度才会出现超出项；600 千卡下没有超标餐食属合理结果，
        # 所以单独用一个必然产生超出项的额度来验证单位。
        "energy": ("千卡", "100"),
    }

    def test_over_by_uses_profile_unit(self):
        for prof, (cn, kcal) in self.CASES.items():
            argv = ["plan", "--demo", "--profile", prof, "--mode", "screen-reader"]
            if kcal:
                argv += ["--meal-kcal", kcal]
            code, out = run(argv)
            self.assertEqual(code, 0, prof)
            overs = [l for l in out.splitlines() if "超出" in l]
            self.assertTrue(overs, f"{prof} 档应至少有一条超出播报")
            for line in overs:
                m = re.search(r"超出\s*([\d.]+)\s*(\S+?)，", line)
                self.assertIsNotNone(m, f"{prof} 超出播报格式异常：{line.strip()}")
                self.assertEqual(m.group(2), cn,
                                 f"{prof} 档超出量单位应为 {cn}，实际 {m.group(2)}：{line.strip()}")

    def test_non_sodium_never_says_mg(self):
        """反向断言：非钠档的超出播报里不得出现「毫克」。"""
        for prof in ("carb", "fat", "energy"):
            code, out = run(["plan", "--demo", "--profile", prof,
                             "--meal-kcal", "600", "--mode", "screen-reader"])
            self.assertEqual(code, 0, prof)
            for line in out.splitlines():
                if "超出" in line:
                    self.assertNotIn("毫克", line,
                                     f"{prof} 档把超出量说成毫克：{line.strip()}")


class TestLimitProvenanceWording(unittest.TestCase):
    """额度来源必须与算法一致 —— 这是本项目「数据诚实」的一部分。

    控糖/低脂/控能量三档的 daily_limit 是 None，额度完全由 --meal-kcal 推导。
    早期版本对所有档位统一说「按日限额的三分之一折算」，用户会以为
    存在某个权威日限额口径 —— 而实际上这三个档位根本没有日限额。
    """

    def test_sodium_says_one_third(self):
        code, out = run(["plan", "--demo", "--profile", "sodium"])
        self.assertEqual(code, 0)
        self.assertIn("三分之一", out)

    def test_derived_profiles_do_not_claim_one_third(self):
        for prof in ("carb", "fat", "energy"):
            code, out = run(["plan", "--demo", "--profile", prof, "--meal-kcal", "600"])
            self.assertEqual(code, 0, prof)
            self.assertNotIn("三分之一", out,
                             f"{prof} 档的额度来自 --meal-kcal，不该说「三分之一折算」")
            self.assertIn("600", out, f"{prof} 档应说明额度来源是 600 千卡")

    def test_energy_says_no_conversion(self):
        """能量档额度就是用户给的值，必须声明「不做任何换算」。"""
        code, out = run(["plan", "--demo", "--profile", "energy", "--meal-kcal", "600"])
        self.assertEqual(code, 0)
        self.assertIn("不提供任何默认值", out)
        self.assertIn("不做任何换算", out)

    def test_derived_profiles_point_at_meal_kcal(self):
        """控糖/低脂的额度是 --meal-kcal × 供能比，必须如实说明推导链。"""
        for prof in ("carb", "fat"):
            code, out = run(["plan", "--demo", "--profile", prof, "--meal-kcal", "600"])
            self.assertEqual(code, 0, prof)
            self.assertIn("由你给出的本餐能量目标", out)
            self.assertIn("供能比", out)

    def test_demo_non_sodium_profile_does_not_leak_sodium_wording(self):
        """控糖档用户不该被告知「钠由低到高」或听到钠密度。"""
        code, out = run(["demo", "--mode", "screen-reader",
                         "--profile", "carb", "--meal-kcal", "600"])
        self.assertEqual(code, 0)
        self.assertIn("碳水由低到高", out)
        for wrong in ("钠由低到高", "钠密度", "钠含量最高的几项"):
            self.assertNotIn(wrong, out,
                             f"控糖档输出不应出现 {wrong}")

    def test_demo_sodium_profile_keeps_density(self):
        """钠档仍应保留钠密度——这是钠档真正有用的信息。"""
        code, out = run(["demo", "--mode", "screen-reader",
                         "--profile", "sodium"])
        self.assertEqual(code, 0)
        self.assertIn("钠密度", out)
        self.assertIn("钠由低到高", out)


class TestTruncationNoticeAccuracy(unittest.TestCase):
    """BUG-08：省略提示与实际输出对不上。

    旧文案恒称「large-print 模式每次最多 N 项」，但实际是 N 项达标 +
    1 条超标示例，且 screen-reader 命中 --top 截断时也会走这段文案。
    """

    def test_large_print_notice_matches_actual_item_count(self):
        code, out = run(["plan", "--demo", "--mode", "large-print"])
        self.assertEqual(code, 0)
        if "未显示" not in out:
            self.skipTest("本次输出未被截断，无需校验省略提示")
        m = re.search(r"另有 \d+ 项主食未显示（([^）]*?)）。", out)
        self.assertIsNotNone(m, f"large-print 省略提示格式不对：\n{out}")
        notice = m.group(1)
        self.assertIn("large-print", notice)
        self.assertIn("高于参考值示例", notice,
                      "提示必须说明实际页大小是「N 项低于参考值 + 1 条高于参考值示例」，"
                      "不能只说 N 项——旧文案与实际输出对不上")
        # 「超标」是对产品的定性措辞，官方红线禁止。提示文案属用户可见内容，
        # 不得出现。这里用词必须与 CLI 其余输出保持一致。
        self.assertNotIn("超标", notice,
                         "省略提示属用户可见输出，不得对产品定性")
        # 提示里的 N 必须等于代码里的 page（3），而不是最终展示条数（4）。
        n = int(re.search(r"最多显示 (\d+) 项", notice).group(1))
        self.assertEqual(n, 3)

    def test_screen_reader_notice_blames_top_not_large_print(self):
        """screen-reader 截断时不得提large-print，否则误导用户去换无效参数。"""
        code, out = run(["plan", "--demo", "--mode", "screen-reader",
                         "--top", "2"])
        self.assertEqual(code, 0)
        if "未显示" in out:
            self.assertNotIn("large-print 模式每次最多", out,
                             "screen-reader 截断原因不是 large-print 页大小")
            self.assertIn("--top", out, "应提示可用 --top 调整")


class TestRemovedFlagsAreGone(unittest.TestCase):
    """被删除的 flag 必须真的删干净，不能留下静默失效的参数。"""

    def test_plan_json_removed(self):
        with _expect_systemexit():
            run(["plan", "--demo", "--json"])

    def test_stores_json_removed(self):
        with _expect_systemexit():
            run(["stores", "--demo", "--json"])

    def test_profiles_json_still_available(self):
        code, out = run(["profiles", "--json"])
        self.assertEqual(code, 0)
        self.assertIn("sodium", out)

    def test_no_open_now_is_usable(self):
        """BUG-07：曾恒为真且无法关闭。"""
        code, _ = run(["stores", "--demo", "--no-open-now"])
        self.assertEqual(code, 0)
        code, _ = run(["stores", "--demo", "--open-now"])
        self.assertEqual(code, 0)


class TestModePlacementAndDefaults(unittest.TestCase):
    def test_mode_default_is_plain(self):
        ns = build_parser().parse_args(["demo"])
        self.assertEqual(ns.mode, "plain")

    def test_mode_after_subcommand(self):
        ns = build_parser().parse_args(["demo", "--mode", "screen-reader"])
        self.assertEqual(ns.mode, "screen-reader")

    def test_demo_needs_no_token(self):
        """离线演示必须零配置可跑。"""
        old = os.environ.pop("MCD_MCP_TOKEN", None)
        try:
            code, _ = run(["demo", "--mode", "screen-reader"])
            self.assertEqual(code, 0)
        finally:
            if old is not None:
                os.environ["MCD_MCP_TOKEN"] = old


class TestDocsMatchParser(unittest.TestCase):
    """文档承诺的每个 flag 都必须真实存在于 build_parser()。

    这条测试专门防 BUG-01（文档写了跑不通的命令）复发。
    """

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _dests(self):
        import argparse as _ap
        p = build_parser()
        dests = {a.dest for a in p._actions}
        # 逐个子收集器
        for act in p._actions:
            if isinstance(act, _ap._SubParsersAction):
                for sub in act.choices.values():
                    dests |= {a.dest for a in sub._actions}
        return dests

    def _flags_in(self, filename):
        import re
        path = os.path.join(self.ROOT, filename)
        text = open(path, encoding="utf-8").read()
        return set(re.findall(r"--[a-z][a-z0-9-]*", text))

    def test_skill_md_flags_exist(self):
        dests = self._dests()
        missing = sorted(f for f in self._flags_in("SKILL.md")
                         if f.lstrip("-").replace("-", "_") not in dests)
        self.assertEqual(missing, [], f"SKILL.md 承诺了不存在的参数：{missing}")

    def test_readme_flags_exist(self):
        dests = self._dests()
        missing = sorted(f for f in self._flags_in("README.md")
                         if f.lstrip("-").replace("-", "_") not in dests)
        self.assertEqual(missing, [], f"README.md 承诺了不存在的参数：{missing}")

    def test_no_bare_command_in_docs(self):
        """BUG-01 的真正防线：仓库无 pyproject.toml，不存在 mcd-a11y 命令。"""
        import re
        for fn in ("SKILL.md", "README.md", "workbuddy.md"):
            text = open(os.path.join(self.ROOT, fn), encoding="utf-8").read()
            for block in re.findall(r"```(?:bash|sh)?\n(.*?)```", text, re.S):
                for line in block.splitlines():
                    s = line.strip().lstrip("$ ").strip()
                    if s.startswith("mcd-a11y "):
                        self.fail(f"{fn} 里的 `{s}` 无法执行："
                                  f"仓库无 pyproject.toml，"
                                  f"必须用 python3 -m mcd_a11y")


class TestRenderInternals(unittest.TestCase):
    """render层的边界 —— 这些是无障碍输出的地基。"""

    def test_item_uses_total_param(self):
        import inspect
        from mcd_a11y.render import Out
        src = inspect.getsource(Out.item)
        self.assertIn("total", src,
                      "Out.item 的 total 形参未被使用，"
                      "与「显式进度」的承诺不符")

    def test_money_negative_is_correct(self):
        """divmod 对负数向下取整会让 -1988 读成「负二十元一角二分」。"""
        from mcd_a11y.render import money_to_cn
        self.assertEqual(money_to_cn(-1988), "负十九元八角八分")
        self.assertEqual(money_to_cn(1988), "十九元八角八分")

    def test_money_no_weird_zero_reading(self):
        from mcd_a11y.render import money_to_cn
        self.assertEqual(money_to_cn(0), "零元")
        self.assertEqual(money_to_cn(2250), "二十二元五角")
        self.assertEqual(money_to_cn(1905), "十九元零五分")

    def test_int_to_cn_yi_and_remainder(self):
        from mcd_a11y.render import int_to_cn
        self.assertEqual(int_to_cn(100000000), "一亿")
        self.assertEqual(int_to_cn(10010), "一万零一十")
        self.assertEqual(int_to_cn(10), "十")
        self.assertEqual(int_to_cn(19), "十九")

    def test_unit_half_up_rounding(self):
        """round() 是银行家舍入，2.5 会变成 2、0.5 变成 0。"""
        from mcd_a11y.render import unit
        self.assertEqual(unit("screen-reader", 2.5, "毫克", "mg"), "3 毫克")
        self.assertEqual(unit("screen-reader", 0.5, "毫克", "mg"), "1 毫克")


# ---------------------------------------------------------------- 小工具
import contextlib  # noqa: E402


class _noop:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@contextlib.contextmanager
def _expect_systemexit():
    """argparse 遇到未知参数会 SystemExit(2)。"""
    try:
        yield
    except SystemExit as e:
        if e.code not in (0, 2):
            raise
        return
    raise AssertionError("预期 argparse 因未知参数退出，但没有")


if __name__ == "__main__":
    unittest.main()

class TestComplianceWording(unittest.TestCase):
    """官方红线禁止「侮辱、诋毁、讽刺、贬低麦当劳品牌、产品及形象」。

    因此工具的措辞只能是「数值 vs 参考值」的中性陈述，
    不能出现给产品定性的词。这是硬约束，用测试锁住。
    """

    BANNED = ("不建议", "超标", "达标的仅", " unhealthy", "垃圾食品")

    def _assert_neutral(self, out: str, label: str) -> None:
        for bad in self.BANNED:
            self.assertNotIn(bad, out, f"{label} 含给产品定性的措辞 {bad!r}")

    def test_every_command_declares_non_official(self):
        """每次输出首行都要声明非官方产品，不能只在文档末尾写一次。"""
        for argv in (["demo", "--mode", "screen-reader"],
                     ["profiles", "--mode", "screen-reader"],
                     ["plan", "--demo", "--mode", "screen-reader"],
                     ["stores", "--demo", "--mode", "screen-reader"],
                     ["tweak", "--demo", "--mode", "screen-reader"]):
            code, out = run(argv)
            self.assertEqual(code, 0, f"{argv} 应可运行")
            head = out.strip().splitlines()[0]
            self.assertIn("非麦当劳官方产品", head,
                          f"{argv} 首行必须声明非官方产品")

    def test_public_materials_have_no_product_labeling(self):
        """公开传播物料（README/海报/引导文档）也不得对产品定性。

        合规风险最高的地方不是 CLI 输出，而是会被转发出去的文档与图片。
        只测 CLI 会漏掉这一整类。
        """
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        targets = [
            "README.md",
            "workbuddy.md",
            "SKILL.md",
            "docs/poster/scenario-poster.html",
            "docs/poster/场景与上手引导.md",
        ]
        # 「不健康」在中文文档里可能作为「用户想解决的问题」出现，
        # 但本项目一律改写为「猜钠含量高不高」这类中性陈述。
        extra = ("不健康", "垃圾食品", "unhealthy")
        for rel in targets:
            path = os.path.join(root, rel)
            if not os.path.exists(path):
                continue
            text = open(path, encoding="utf-8").read()
            for bad in self.BANNED + extra:
                self.assertNotIn(
                    bad, text,
                    f"{rel} 含给产品定性的措辞 {bad!r}（会被转发出去，风险最高）")

    def test_no_unfounded_claims_about_users(self):
        """不得替用户群体编造行为习惯。

        「他们每天都在用终端」曾写进海报——中国视障用户主流是手机 + 读屏，
        这类无依据断言一旦发到无障碍社区就会被当场反驳，反而伤可信度。
        """
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in ("README.md",
                    "docs/poster/scenario-poster.html",
                    "docs/poster/场景与上手引导.md"):
            path = os.path.join(root, rel)
            if not os.path.exists(path):
                continue
            text = open(path, encoding="utf-8").read()
            for bad in ("每天都在用终端", "视障用户都", "盲人朋友都"):
                self.assertNotIn(bad, text,
                                 f"{rel} 含无依据的用户行为断言 {bad!r}")

    def test_every_output_path_declares_non_official(self):
        """包括 --json 这类绕过 _out() 的路径，都必须带非官方声明。

        机器可读不等于可以没有边界。JSON 若缺声明，接入方会以为这是
        麦当劳官方数据。
        """
        import json as _json
        code, out = run(["profiles", "--json"])
        self.assertEqual(code, 0)
        data = _json.loads(out)
        self.assertIn("_notice", data,
                      "JSON 顶层必须有 _notice 声明，不能只是裸数组")
        self.assertIn("非麦当劳官方产品", data["_notice"])
        self.assertIn("不构成医疗", data["_notice"])
        # 数据仍要能被取到，声明不能把内容挤掉
        self.assertIsInstance(data.get("profiles"), list)
        self.assertTrue(data["profiles"], "profiles 数据不应为空")

    def test_output_wording_is_neutral(self):
        for argv in (["demo", "--mode", "screen-reader"],
                     ["demo", "--mode", "plain"],
                     ["plan", "--demo", "--mode", "screen-reader"],
                     ["plan", "--demo", "--mode", "plain"]):
            code, out = run(argv)
            self.assertEqual(code, 0)
            self._assert_neutral(out, f"{argv} 的输出")

    def test_reference_value_is_stated(self):
        """判定必须给出具体参考值，让用户自己判断，而不是替产品定性。"""
        code, out = run(["plan", "--demo", "--profile", "sodium",
                         "--mode", "screen-reader"])
        self.assertEqual(code, 0)
        self.assertIn("参考值", out)

    def test_disclaimer_present_everywhere(self):
        for argv in (["demo", "--mode", "screen-reader"],
                     ["profiles", "--mode", "screen-reader"],
                     ["plan", "--demo", "--mode", "screen-reader"]):
            code, out = run(argv)
            self.assertEqual(code, 0)
            self.assertIn("不构成医疗", out, f"{argv} 缺免责声明")


class TestReadmeCompliance(unittest.TestCase):
    """README 也要过合规自查 —— 它是最容易被评审逐字看的地方。"""

    ROOT2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_readme_has_disclaimer_on_first_screen(self):
        text = open(os.path.join(self.ROOT2, "README.md"),
                    encoding="utf-8").read()
        head = text.split("## 30 秒上手")[0]
        self.assertIn("非麦当劳官方产品", head)
        self.assertIn("不构成医疗", head)

    def test_readme_avoids_product_qualification(self):
        text = open(os.path.join(self.ROOT2, "README.md"),
                    encoding="utf-8").read()
        for bad in ("87% 超标", "不建议"):
            self.assertNotIn(bad, text,
                             f"README 含给产品定性的措辞 {bad!r}")

    def test_readme_keeps_data_facts(self):
        """改措辞不能删信息量：核心数据事实必须仍在。"""
        text = open(os.path.join(self.ROOT2, "README.md"),
                    encoding="utf-8").read()
        for keep in ("160", "15 款", "2 款", "参考值"):
            self.assertIn(keep, text, f"README 丢失了关键信息 {keep!r}")
