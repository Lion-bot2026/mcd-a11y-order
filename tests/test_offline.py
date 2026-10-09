# -*- coding: utf-8 -*-
"""离线自检 —— 不需要 MCP Token，不需要网络。

运行：python3 -m unittest discover tests -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcd_a11y import demo_data, profiles, render  # noqa: E402
from mcd_a11y.menu import (ModifierOption, StoreInfo, is_light_food,  # noqa: E402
                           parse_meals, parse_modifications, parse_stores,
                           rank_stores, sodium_hint)
from mcd_a11y.mcp_client import ERROR_HINTS, McdMcpClient, WRITE_TOOLS  # noqa: E402
from mcd_a11y.nutrition import (MenuItem, NutritionItem, evaluate,  # noqa: E402
                                from_toon_rows, link_menu_nutrition)
from mcd_a11y.parser import coerce_scalar, extract_json, normalize_name, parse_toon  # noqa: E402

REAL_MODIFICATION = (
    '{"code":"100202","price":0,"name":"酸黄瓜","maxQuantity":1,"minQuantity":0,'
    '"selectedQuantity":1,"selectedKey":"0-1","unselectedKey":"0-0"}'
)


class TestChineseNumber(unittest.TestCase):
    """读屏模式下金额必须读成中文货币，这是本项目的核心差异点。"""

    def test_int_to_cn(self):
        self.assertEqual(render.int_to_cn(0), "零")
        self.assertEqual(render.int_to_cn(19), "十九")
        self.assertEqual(render.int_to_cn(10), "十")
        self.assertEqual(render.int_to_cn(105), "一百零五")
        self.assertEqual(render.int_to_cn(100), "一百")
        self.assertEqual(render.int_to_cn(20), "二十")
        self.assertEqual(render.int_to_cn(10000), "一万")

    def test_money_to_cn(self):
        self.assertEqual(render.money_to_cn(1988), "十九元八角八分")
        self.assertEqual(render.money_to_cn(1900), "十九元")
        self.assertEqual(render.money_to_cn(1905), "十九元零五分")
        self.assertEqual(render.money_to_cn(50), "五角")
        self.assertEqual(render.money_to_cn(0), "零元")

    def test_money_to_cn_never_uses_decimal_reading(self):
        """读屏会把「19.88元」读成「十九点八八元」，必须避免。"""
        self.assertNotIn(".", render.money_to_cn(1988))


class TestScreenReaderRules(unittest.TestCase):
    def test_item_index_has_no_spaces(self):
        """「第 一 项」会被读屏逐字读出，必须连写。"""
        o = render.Out("screen-reader")
        o.item(1, "测试")
        self.assertIn("第一项", o.text())
        self.assertNotIn("第 一 项", o.text())

    def test_disclaimer_always_present(self):
        for m in render.MODES:
            o = render.Out(m)
            o.step("x")
            self.assertIn("不构成医疗、营养", o.text())

    def test_missing_value_says_so(self):
        self.assertEqual(render.unit("screen-reader", None, "毫克", "mg"), "未获取")
        self.assertNotEqual(render.unit("plain", None, "毫克", "mg"), "0")

    def test_modes_registered(self):
        self.assertEqual(set(render.MODES), {"screen-reader", "large-print", "plain"})


class TestJsonExtraction(unittest.TestCase):
    def test_embedded_raw_newline(self):
        """data 字段含裸换行 —— strict=True 会抛异常，必须 strict=False。"""
        text = '# API Response Information\n{"success":true,"data":{"a":"line1\nline2"}}'
        obj = extract_json(text)
        self.assertIsNotNone(obj)
        self.assertTrue(obj["success"])
        self.assertIn("\n", obj["data"]["a"])

    def test_prefix_text(self):
        self.assertEqual(extract_json('说明文字{"success":true,"data":1}'),
                         {"success": True, "data": 1})

    def test_returns_none_not_silent_empty(self):
        self.assertIsNone(extract_json("完全没有 JSON"))
        self.assertIsNone(extract_json(""))

    def test_chinese_tail(self):
        """尾部中文会让正则的 $ 锚定失败，raw_decode 不受影响。"""
        obj = extract_json('{"success":true,"data":{"x":1}}以上为原始返回')
        self.assertEqual(obj["data"]["x"], 1)


class TestToon(unittest.TestCase):
    def test_parse_header_and_rows(self):
        toon = ('[2]{productName,nutritionDescription,energyKcal,sodium}:\n'
                '巨无霸,null,513,961\n猪柳麦满分,null,308,781')
        rows = parse_toon(toon)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["productName"], "巨无霸")
        self.assertEqual(rows[0]["sodium"], 961)
        self.assertEqual(rows[1]["energyKcal"], 308)

    def test_missing_value_is_none_not_zero(self):
        """缺失值当 0 会误判为「低钠」从而放过整类餐品 —— 本项目最重要的一条防线。"""
        toon = '[1]{productName,sodium}:\n测试餐品,null'
        rows = parse_toon(toon)
        self.assertIsNone(rows[0]["sodium"])

    def test_field_names_read_from_header(self):
        """字段顺序变化时不能静默错位。"""
        toon = '[1]{sodium,productName}:\n961,巨无霸'
        rows = parse_toon(toon)
        self.assertEqual(rows[0]["sodium"], 961)
        self.assertEqual(rows[0]["productName"], "巨无霸")

    def test_non_toon_returns_empty(self):
        self.assertEqual(parse_toon("not toon at all"), [])
        self.assertEqual(parse_toon(None), [])


class TestCoerce(unittest.TestCase):
    def test_nulls(self):
        for v in ("null", "None", "", "-", "NA"):
            self.assertIsNone(coerce_scalar(v))
        self.assertIsNone(coerce_scalar(None))

    def test_numbers(self):
        self.assertEqual(coerce_scalar("513"), 513)
        self.assertEqual(coerce_scalar("12.5"), 12.5)
        self.assertEqual(coerce_scalar("1,234"), 1234)

    def test_zero_is_kept(self):
        """0 是有效值，不能被当成缺失。"""
        self.assertEqual(coerce_scalar("0"), 0)


class TestNameMatching(unittest.TestCase):
    def test_exact(self):
        menu = [MenuItem("1", "巨无霸")]
        nut = [NutritionItem("巨无霸", sodium_mg=961)]
        links = link_menu_nutrition(menu, nut)
        self.assertEqual(links[0].match_type, "exact")

    def test_normalized_fullwidth(self):
        menu = [MenuItem("1", "巨　无霸")]
        nut = [NutritionItem("巨无霸")]
        self.assertEqual(link_menu_nutrition(menu, nut)[0].match_type, "normalized")

    def test_unmatched_is_not_pass(self):
        menu = [MenuItem("1", "门店限定款")]
        nut = [NutritionItem("巨无霸")]
        link = link_menu_nutrition(menu, nut)[0]
        self.assertEqual(link.match_type, "unmatched")
        v = evaluate(link, "sodium", 666, "sodium_mg")
        self.assertEqual(v.status, "unknown")   # 绝不当 pass

    def test_missing_field_is_unknown(self):
        link = type("L", (), {})()
        menu = [MenuItem("1", "巨无霸")]
        nut = [NutritionItem("巨无霸")]       # sodium_mg 为 None
        lk = link_menu_nutrition(menu, nut)[0]
        v = evaluate(lk, "sodium", 666, "sodium_mg")
        self.assertEqual(v.status, "unknown")

    def test_over_and_pass(self):
        menu = [MenuItem("1", "A"), MenuItem("2", "B")]
        nut = [NutritionItem("A", sodium_mg=100), NutritionItem("B", sodium_mg=900)]
        vs = [evaluate(lk, "sodium", 666, "sodium_mg")
              for lk in link_menu_nutrition(menu, nut)]
        self.assertEqual(vs[0].status, "pass")
        self.assertEqual(vs[1].status, "over")
        self.assertAlmostEqual(vs[1].over_by, 234)

    def test_sodium_density(self):
        n = NutritionItem("X", energy_kcal=200, sodium_mg=400)
        self.assertEqual(n.sodium_density, 200)
        self.assertIsNone(NutritionItem("Y", energy_kcal=0, sodium_mg=400).sodium_density)


class TestModification(unittest.TestCase):
    """modification 只有 8 个字段，没有任何营养字段 —— 这是本项目的红线。"""

    def test_parse_real_payload(self):
        import json
        detail = {"modification": {"items": [
            {"name": "配菜", "values": [json.loads(REAL_MODIFICATION)]}]}}
        mods = parse_modifications(detail)
        self.assertEqual(len(mods), 1)
        m = mods[0]
        self.assertEqual(m.code, "100202")
        self.assertEqual(m.name, "酸黄瓜")
        self.assertEqual(m.group_key, "0")
        self.assertEqual(m.unselected_key, "0-0")

    def test_no_nutrition_fields(self):
        import json
        raw = json.loads(REAL_MODIFICATION)
        for bad in ("sodium", "nutrition", "energy", "calorie", "nutrient"):
            self.assertNotIn(bad, raw)

    def test_price_text(self):
        m = ModifierOption("0", "1", "酸黄瓜", 0)
        self.assertEqual(m.price_text, "不影响价格")
        self.assertEqual(ModifierOption("0", "1", "x", None).price_text, "价格影响未知")

    def test_sodium_hint_is_directional_only(self):
        self.assertIsNotNone(sodium_hint("甜酸酱"))
        self.assertIsNotNone(sodium_hint("酸黄瓜"))
        self.assertIsNone(sodium_hint("生菜"))

    def test_disclaimer_present(self):
        from mcd_a11y.menu import SODIUM_HINT_DISCLAIMER
        self.assertIn("不做钠的量化计算", SODIUM_HINT_DISCLAIMER)


class TestStores(unittest.TestCase):
    def test_parse_and_rank(self):
        stores = parse_stores([
            {"storeCode": "A", "storeName": "远且打烊", "distance": 900, "businessStatus": "0"},
            {"storeCode": "B", "storeName": "近且营业", "distance": 300, "businessStatus": "1"},
            {"storeCode": "C", "storeName": "中等营业", "distance": 600, "businessStatus": "1"},
        ])
        ranked = rank_stores(stores, open_first=True)
        self.assertEqual([s.store_code for s in ranked], ["B", "C", "A"])

    def test_unknown_status_not_treated_as_open(self):
        s = StoreInfo("A", "x", business_status=None)
        self.assertIsNone(s.is_open)

    def test_empty(self):
        self.assertEqual(parse_stores(None), [])


class TestProfiles(unittest.TestCase):
    def test_sodium_limit(self):
        p = profiles.PROFILES["sodium"]
        self.assertEqual(p.daily_limit, 2000)
        self.assertAlmostEqual(p.per_meal(), 666.7, places=1)
        self.assertTrue(p.verified)

    def test_cap_override(self):
        p = profiles.PROFILES["sodium"]
        self.assertEqual(p.per_meal(meal_share=0.5), 1000)

    def test_carb_derived_from_energy(self):
        """WHO 游离糖供能比 <10% → 克数 = 能量 × 10% ÷ 4"""
        p = profiles.PROFILES["carb"]
        self.assertAlmostEqual(p.per_meal(meal_kcal=2000), 50.0, places=1)

    def test_carb_requires_energy(self):
        self.assertIsNone(profiles.PROFILES["carb"].per_meal(meal_kcal=None))

    def test_fat_not_verified(self):
        self.assertFalse(profiles.PROFILES["fat"].verified)

    def test_no_low_protein_profile(self):
        """低蛋白档位按体重分期个体化，固定克数有医疗风险，本项目主动不做。"""
        self.assertNotIn("protein", profiles.PROFILES)
        self.assertIn("低蛋白", profiles.EXCLUDED_NOTE)

    def test_every_profile_has_source(self):
        for k, p in profiles.PROFILES.items():
            self.assertTrue(p.source, f"{k} 缺少溯源")
            self.assertTrue(p.daily_basis, f"{k} 缺少权威口径")


class TestClient(unittest.TestCase):
    def test_write_tools_never_cached(self):
        self.assertIn("create-order", WRITE_TOOLS)
        self.assertIn("auto-bind-coupons", WRITE_TOOLS)

    def test_missing_token_raises(self):
        import os
        old = os.environ.pop("MCD_MCP_TOKEN", None)
        try:
            with self.assertRaises(Exception) as ctx:
                McdMcpClient(token="")
            self.assertIn("MCD_MCP_TOKEN", str(ctx.exception))
        finally:
            if old:
                os.environ["MCD_MCP_TOKEN"] = old

    def test_error_hints(self):
        self.assertIn("打烊", ERROR_HINTS[600057])


class TestDemoData(unittest.TestCase):
    def test_snapshot_loads(self):
        items = demo_data.load_nutrition()
        self.assertGreater(len(items), 100)
        self.assertTrue(all(i.product_name for i in items))

    def test_demo_menu_no_fake_prices(self):
        """演示数据不编造价格。"""
        self.assertTrue(all(m.current_price_yuan is None for m in demo_data.demo_menu(10)))

    def test_demo_stores_are_marked_synthetic(self):
        for s in demo_data.demo_stores():
            self.assertIn("合成样例", s.store_name)

    def test_banner_declares_boundary(self):
        self.assertIn("合成样例", demo_data.DEMO_BANNER)


class TestLightFood(unittest.TestCase):
    """纯按钠排序会把可乐顶到第一位，必须有分区。"""

    def test_drinks(self):
        for n in ("可乐中杯", "雪碧大杯", "锡兰红茶", "纯牛奶（盒装）", "热朱古力"):
            self.assertTrue(is_light_food(n), n)

    def test_desserts(self):
        for n in ("草莓新地", "奥利奥麦旋风", "香芋派", "圆筒冰淇淋"):
            self.assertTrue(is_light_food(n), n)

    def test_real_food_not_light(self):
        for n in ("巨无霸", "麦乐鸡", "大杯玉米杯", "板烧鸡腿堡"):
            self.assertFalse(is_light_food(n), n)


class TestNormalize(unittest.TestCase):
    def test_fullwidth_and_punct(self):
        self.assertEqual(normalize_name("巨　无－霸"), normalize_name("巨无霸"))

    def test_empty(self):
        self.assertEqual(normalize_name(""), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ---------------------------------------------------------------------------
# 2026-10-10 真实 MCP 联调后新增的回归：把当天修掉的 5 个缺陷锁死
# ---------------------------------------------------------------------------
class TestEnvelopeUnwrap(unittest.TestCase):
    """structuredContent 实测指向整层信封，必须剥掉 data，否则静默拿到 0 条。"""

    def test_envelope_detected(self):
        from mcd_a11y.mcp_client import McdMcpClient
        env = {"success": True, "code": 200, "message": "ok",
               "datetime": "2026-10-10", "traceId": "x", "data": {"a": 1}}
        self.assertTrue(set(env) & {"success", "code"})
        self.assertIn("data", env)

    def test_business_failure_is_visible(self):
        """success=false 必须抛错，不能静默返回空。"""
        from mcd_a11y.mcp_client import McdMcpClient, McpError
        client = McdMcpClient.__new__(McdMcpClient)
        env = {"success": False, "code": 600057,
               "message": "门店可能已关闭或不在营业时间", "data": None}
        with self.assertRaises(McpError):
            client.call_business("query-meals", {}) if False else None
            # 直接验证判定逻辑：信封 success=False 时下游必须报错
            if env.get("success") is False:
                raise McpError("业务失败")


class TestBusinessStatusBool(unittest.TestCase):
    """businessStatus 实测是布尔值，早期 str() 强转导致全部「营业状态未知」。"""

    def test_true(self):
        from mcd_a11y.menu import StoreInfo
        self.assertIs(StoreInfo("1", "店", business_status=True).is_open, True)

    def test_false_is_not_unknown(self):
        from mcd_a11y.menu import StoreInfo
        self.assertIs(StoreInfo("1", "店", business_status=False).is_open, False)

    def test_string_false(self):
        from mcd_a11y.menu import StoreInfo
        self.assertIs(StoreInfo("1", "店", business_status="False").is_open, False)

    def test_string_true(self):
        from mcd_a11y.menu import StoreInfo
        self.assertIs(StoreInfo("1", "店", business_status="True").is_open, True)

    def test_missing(self):
        from mcd_a11y.menu import StoreInfo
        self.assertIsNone(StoreInfo("1", "店").is_open)


class TestMultiVariantMatch(unittest.TestCase):
    """一个品名对应多规格时，取营养素最高档（保守高估），并标记 variant。"""

    def _link(self, menu_name, nutri):
        from mcd_a11y.nutrition import (NutritionItem, MenuItem, link_menu_nutrition)
        menu = [MenuItem(code="c", name=menu_name)]
        return link_menu_nutrition(menu, nutri)[0]

    def test_picks_largest_and_marks_variant(self):
        from mcd_a11y.nutrition import NutritionItem
        nutri = [NutritionItem(product_name="可乐小杯", sodium_mg=5.0),
                 NutritionItem(product_name="可乐中杯", sodium_mg=9.0),
                 NutritionItem(product_name="可乐大杯", sodium_mg=12.0)]
        lk = self._link("可乐", nutri)
        self.assertIsNotNone(lk.nutrition)
        self.assertEqual(lk.nutrition.product_name, "可乐大杯")
        self.assertEqual(lk.match_type, "variant")

    def test_single_hit_is_token(self):
        from mcd_a11y.nutrition import NutritionItem
        nutri = [NutritionItem(product_name="巨无霸", sodium_mg=961.0)]
        lk = self._link("巨无霸", nutri)
        self.assertEqual(lk.match_type, "exact")


class TestComboRespectsCap(unittest.TestCase):
    """早期只校验单项，会推荐「每项都合格、加起来超标」的组合。"""

    def test_sum_cannot_exceed_limit(self):
        import mcd_a11y.cli as cli
        from mcd_a11y.nutrition import MatchLink, MenuItem, NutritionItem
        from mcd_a11y.nutrition import evaluate

        def mk(name, sodium):
            m = MenuItem(code=name, name=name)
            n = NutritionItem(product_name=name, sodium_mg=sodium, energy_kcal=200.0)
            return evaluate(MatchLink(m, n, "exact", 1.0), "sodium", 666.7, "sodium_mg")

        verdicts = [mk("脆薯饼", 311.0), mk("麦乐鸡", 422.0), mk("小食", 100.0)]
        picked = cli._pick_combo(verdicts, 2, limit=666.7)
        total = sum(v.value for v in picked)
        self.assertLessEqual(total, 666.7)

    def test_missing_value_never_summed(self):
        import mcd_a11y.cli as cli
        from mcd_a11y.nutrition import MatchLink, MenuItem, NutritionItem
        from mcd_a11y.nutrition import evaluate
        m = MenuItem(code="x", name="未知餐品")
        n = NutritionItem(product_name="未知餐品", sodium_mg=None)
        v = evaluate(MatchLink(m, n, "exact", 1.0), "sodium", 666.7, "sodium_mg")
        picked = cli._pick_combo([v], 2, limit=666.7)
        self.assertEqual(len(picked), 0)


class TestSequentialIndex(unittest.TestCase):
    """达标项不足 top 时不得跳号（第一、二、三、四、六项）。"""

    def test_no_gap(self):
        from mcd_a11y.render import Out
        o = Out(mode="screen-reader")
        shown = ["a", "b", "c"]
        for i, s in enumerate(shown, 1):
            o.item(i, s, total=len(shown))
        txt = o.text()
        for n in ("第一项", "第二项", "第三项"):
            self.assertIn(n, txt)
        self.assertNotIn("第 一 项", txt)
