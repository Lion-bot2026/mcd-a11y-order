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
