# -*- coding: utf-8 -*-
"""麦麦读得到 · 命令行入口。

设计取向：一条命令就能跑出可读的结果，`--demo` 不需要任何配置。
唯一会产生真实副作用的是 `order`，必须显式 --confirm。
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import demo_data
from . import render
from .menu import (SODIUM_HINT_DISCLAIMER, is_light_food, parse_meals, parse_modifications,
                   parse_stores, rank_stores, sodium_hint)
from .mcp_client import McpError, McdMcpClient
from .nutrition import evaluate, link_menu_nutrition
from .parser import parse_toon
from .profiles import EXCLUDED_NOTE, PROFILES, describe_profiles, get_profile
from .render import Out, int_to_cn, money, money_to_cn, unit

APP = "mcd-a11y"
NO_FACILITY_NOTE = (
    "麦当劳 MCP 不提供门店无障碍设施信息（坡道、无障碍卫生间、低位柜台等），"
    "本工具无法核实，请到店前致电门店确认。"
)


# --------------------------------------------------------------------------
# 通用
# --------------------------------------------------------------------------

def _out(mode: str) -> Out:
    return Out(mode)


def _open_store_note(o: Out, s, index: int = 1, total: int | None = None) -> None:
    st = s.is_open
    state = "正在营业" if st is True else ("已打烊" if st is False else "营业状态未知")
    dist = f"，距离 {int(s.distance)} 米" if isinstance(s.distance, (int, float)) else ""
    hours = ""
    if s.business_end:
        hours = f"，营业至 {s.business_end}"
    o.item(index, f"{s.store_name}。{state}{dist}{hours}", total=total)


def _split_meal_and_light(verdicts, min_kcal: float):
    """把候选项拆成「餐食」与「小食饮品」。

    纯按钠升序会把可乐（钠 0 毫克）顶到第一位，对「这一餐吃什么」毫无帮助。
    本项目用两条启发式规则把饮品与小食分开：名称关键词命中饮品，或能量低于阈值。
    这是本项目在实测中发现并修正的一个真实产品缺陷。
    """
    meal, light = [], []
    for v in verdicts:
        n = v.link.nutrition
        kcal = n.energy_kcal if n else None
        if is_light_food(v.link.menu_item.name) or kcal is None or kcal < min_kcal:
            light.append(v)
        else:
            meal.append(v)
    return meal, light


def _uname(mode: str, profile) -> str:
    """读屏模式用中文单位（毫克），普通模式用符号（mg）。"""
    return profile.unit_cn if mode == "screen-reader" else profile.unit_sym


def _pick_combo(verdicts, size: int = 2, limit: float | None = None):
    """挑组合。两条硬约束：

    1. 避免「薯条小份 + 薯条大份」这种同款不同规格的搭配。
    2. **合计不得超过本餐额度** —— 实测发现早期版本只校验单项，
       会推荐「311 + 422 = 733 毫克」这种合计超出 666.7 毫克额度的组合。
       对限钠人群来说，这种「每项都合格、加起来超标」的建议比不推荐更危险。

    额度为 None 时只做第 1 条约束。
    """
    picked: list = []
    total = 0.0
    for v in verdicts:
        name = v.link.menu_item.name
        if any(_share_stem(name, p.link.menu_item.name) for p in picked):
            continue
        val = v.value if v.value is not None else None
        if limit is not None:
            # 任一成分数据缺失就不敢加总，宁可不推荐
            if val is None:
                continue
            if total + val > limit:
                continue
            total += val
        picked.append(v)
        if len(picked) >= size:
            break
    return picked


def _share_stem(a: str, b: str) -> bool:
    """两个名字共享前 2 个字以上且长度接近时视为同款。"""
    a, b = str(a or ""), str(b or "")
    if not a or not b:
        return False
    n = min(len(a), len(b), 3)
    return a[:n] == b[:n] and abs(len(a) - len(b)) <= 3


def _status_text(mode: str, v) -> str:
    if v.status == "pass":
        return "可以选" if mode == "screen-reader" else "✓ 通过"
    if v.status == "over":
        over = unit(mode, v.over_by, v.link and "", "")
        return "超出额度，不建议" if mode == "screen-reader" else "✗ 超出"
    return "数据缺失，未评估" if mode == "screen-reader" else "— 未评估"


# --------------------------------------------------------------------------
# 命令：profiles
# --------------------------------------------------------------------------

def cmd_profiles(args) -> int:
    o = _out(args.mode)
    o.title("可用的饮食档位")
    rows = describe_profiles()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for i, r in enumerate(rows, 1):
        o.step(f"第 {int_to_cn(i)} 档，{r['名称']}（{r['档位']}）")
        o.note(f"日限额：{r['日限额']}")
        o.note(f"权威口径：{r['权威口径']}")
        o.note(f"溯源：{r['溯源']}（已核实：{r['已核实']}）")
        if r["数据边界"]:
            o.boundary(r["数据边界"])
        o.blank()
    o.boundary(EXCLUDED_NOTE)
    print(o.text())
    return 0


# --------------------------------------------------------------------------
# 命令：stores
# --------------------------------------------------------------------------

def cmd_stores(args) -> int:
    o = _out(args.mode)
    if args.demo:
        stores = demo_data.demo_stores()
        o.boundary(demo_data.DEMO_BANNER)
    else:
        client = McdMcpClient()
        raw = client.call_business("query-nearby-stores", {
            "searchType": 2, "beType": args.be_type,
            "city": args.city, "keyword": args.keyword,
        })
        stores = parse_stores(raw)

    stores = rank_stores(stores, open_first=args.open_now)
    open_cnt = sum(1 for s in stores if s.is_open is True)
    o.step(f"共检索到 {len(stores)} 家门店，其中 {open_cnt} 家正在营业。按营业状态与距离排列。")
    for i, s in enumerate(stores, 1):
        _open_store_note(o, s, index=i, total=len(stores))
    o.blank()
    o.boundary(NO_FACILITY_NOTE)
    print(o.text())
    return 0


# --------------------------------------------------------------------------
# 命令：plan（主命令）
# --------------------------------------------------------------------------

def cmd_plan(args) -> int:
    o = _out(args.mode)
    profile = get_profile(args.profile)

    # ---- 门店 ----
    if args.demo:
        o.boundary(demo_data.DEMO_BANNER)
        stores = rank_stores(demo_data.demo_stores(), open_first=True)
    else:
        client = McdMcpClient()
        stores = parse_stores(client.call_business("query-nearby-stores", {
            "searchType": 2, "beType": args.be_type,
            "city": args.city, "keyword": args.keyword,
        }))
        stores = rank_stores(stores, open_first=True)

    if not stores:
        print("未检索到门店，请检查城市名与关键词（两者必须同时提供）。")
        return 1
    store = stores[0]

    o.step(f"第一步，选门店。共 {len(stores)} 家，优先营业中、按距离由近到远。")
    for i, s in enumerate(stores[:3], 1):
        _open_store_note(o, s, index=i, total=min(3, len(stores)))
    o.boundary(NO_FACILITY_NOTE)
    o.blank()

    # ---- 营养 + 菜单 ----
    if args.demo:
        nutrition = demo_data.load_nutrition()
        menu = demo_data.demo_menu(limit=args.scan)
    else:
        client = McdMcpClient()
        toon = client.call_business("list-nutrition-foods", {})
        nutrition = _nutrition_from(toon)
        raw_menu = client.call_business("query-meals", {
            "storeCode": store.store_code, "orderType": 1, "beType": args.be_type,
        })
        menu = parse_meals(raw_menu, store_code=store.store_code)

    links = link_menu_nutrition(menu, nutrition)

    # ---- 额度 ----
    limit = _resolve_limit(args, profile)
    if limit is None:
        o.boundary(
            f"档位「{profile.label}」需要能量目标才能推导额度，"
            f"请加 --meal-kcal 指定本餐能量目标，或改用 sodium 档位。"
        )
        print(o.text())
        return 1

    un = _uname(args.mode, profile)
    o.step(
        f"第二步，这一餐可以吃什么。当前档位，{profile.label}。"
        f"日限额 {profile.daily_limit:g} {un}，本餐额度 {limit:g} {un}。"
        if profile.daily_limit else
        f"第二步，这一餐可以吃什么。当前档位，{profile.label}。本餐额度 {limit:g} {un}。"
    )
    o.boundary(
        "本餐额度按日限额的三分之一折算，这是工程假设、不是权威标准，"
        "可用 --sodium-cap / --meal-kcal 覆盖。"
    )
    for c in getattr(profile, "caveats", ()):
        o.boundary(c)
    o.blank()

    verdicts = [evaluate(lk, profile.key, limit, profile.field) for lk in links]
    verdicts.sort(key=lambda v: (
        {"pass": 0, "over": 1, "unknown": 2}[v.status],
        v.value if v.value is not None else 10 ** 9,
    ))

    meal, light = _split_meal_and_light(verdicts, args.min_kcal)

    def _line(v):
        val = unit(args.mode, v.value, profile.unit_cn, profile.unit_sym)
        line = f"{v.link.menu_item.name}。"
        n = v.link.nutrition
        if n is not None:
            line += (f"能量 {unit(args.mode, n.energy_kcal, '千卡', 'kcal')}。"
                     f"{profile.value_cn} {val}。")
            if profile.key == "sodium" and n.sodium_density is not None:
                line += f"钠密度每百千卡 {unit(args.mode, n.sodium_density, '毫克', 'mg')}。"
        return line + _status_text(args.mode, v)

    # 序号必须是「显示序号」连续递增 —— 早期版本用 args.top 作为第二段起始值，
    # 当达标项不足 top 时会跳号（第一、二、三、四、六…），读屏用户会以为漏了一项。
    shown: list = []
    passed_meal = [x for x in meal if x.status == "pass"][:args.top]
    over_meal = [x for x in meal if x.status == "over"][-3:]
    shown = passed_meal + over_meal
    for i, v in enumerate(shown, 1):
        o.item(i, _line(v), total=len(shown))

    unassessed = sum(1 for v in verdicts if v.status == "unknown")
    if unassessed:
        o.blank()
        o.boundary(f"另有 {unassessed} 项餐品未获取到营养数据，未纳入评估（既不当合格也不当不合格）。")
    variant_n = sum(1 for v in shown
                    if getattr(v.link, "match_type", "") == "variant")
    if variant_n:
        o.boundary(
            f"其中 {variant_n} 项按品名匹配到多个规格（如「可乐」对应小杯/中杯/大杯），"
            f"已取营养素最高的一档，属于保守高估，不是精确值。")
    if light:
        o.boundary(f"另有 {len(light)} 项甜品与饮品（按名称识别，或能量低于 "
                   f"{args.min_kcal:g} 千卡）未计入主餐建议。")

    # ---- 建议组合 ----
    passed = _pick_combo([v for v in meal if v.status == "pass"], 2, limit=limit)
    if passed:
        o.blank()
        o.step("第三步，建议组合。")
        total_val = sum(v.value for v in passed if v.value is not None)
        total_kcal = sum(v.link.nutrition.energy_kcal for v in passed
                         if v.link.nutrition and v.link.nutrition.energy_kcal)
        names = "，加".join(v.link.menu_item.name for v in passed)
        o.note(f"{names}。")
        o.note(f"合计{profile.value_cn} {unit(args.mode, round(total_val, 1), profile.unit_cn, profile.unit_sym)}"
               f"，合计能量 {unit(args.mode, round(total_kcal), '千卡', 'kcal')}。")
        o.boundary("价格请以官方核价为准，本工具不估算金额。")

    o.blank()
    o.step("说「下单」不会自动执行。要继续，请先运行 quote 核价，再运行 order 并加 --confirm。")
    print(o.text())
    return 0


def _nutrition_from(toon: Any):
    from .nutrition import from_toon_rows
    if isinstance(toon, str):
        return from_toon_rows(parse_toon(toon))
    if isinstance(toon, dict):
        inner = toon.get("data")
        if isinstance(inner, str):
            return from_toon_rows(parse_toon(inner))
        if isinstance(inner, list):
            return from_toon_rows(inner)
        if isinstance(inner, dict):
            for v in inner.values():
                if isinstance(v, str) and v.lstrip().startswith("["):
                    return from_toon_rows(parse_toon(v))
    return []


def _resolve_limit(args, profile) -> float | None:
    if profile.key == "sodium" and args.sodium_cap is not None:
        return args.sodium_cap
    return profile.per_meal(meal_kcal=args.meal_kcal)


# --------------------------------------------------------------------------
# 命令：tweak（特制）
# --------------------------------------------------------------------------

def cmd_tweak(args) -> int:
    o = _out(args.mode)
    if args.demo:
        o.boundary(demo_data.DEMO_BANNER)
        mods = demo_data.demo_modifications()
    else:
        client = McdMcpClient()
        detail = client.call_business("query-meal-detail", {
            "code": args.code, "storeCode": args.store,
            "orderType": 1, "beType": args.be_type,
        })
        mods = parse_modifications(detail)

    if not mods:
        o.boundary("该餐品未返回可特制项，或官方接口未提供 modification 数据。不做推测。")
        print(o.text())
        return 0

    o.step(f"这一餐可以这样调整。共 {len(mods)} 个可调项。")
    for i, m in enumerate(mods, 1):
        price_txt = m.price_text
        if args.mode == "screen-reader":
            price_txt = ("不影响价格" if m.price == 0 else
                         ("价格影响未知" if m.price is None else
                          f"{'增加' if m.price > 0 else '减少'} {money_to_cn(abs(int(m.price * 100)))}"))
        sel = "默认包含" if m.is_default_selected else "默认不含"
        line = f"{m.name}。{sel}。{price_txt}。"
        o.item(i, line, total=len(mods))
        hint = sodium_hint(m.name)
        if hint:
            o.note(f"提示：{hint}。")

    o.blank()
    o.boundary(SODIUM_HINT_DISCLAIMER)
    print(o.text())
    return 0


# --------------------------------------------------------------------------
# 命令：quote / order
# --------------------------------------------------------------------------

def cmd_quote(args) -> int:
    """官方核价。金额单位是「分」。"""
    client = McdMcpClient()
    items = json.loads(args.items)
    for it in items:
        if "productCode" not in it:
            print("错误：items 元素必须包含 productCode。写成 code/mealCode 不会报错，"
                  "但会静默返回 price=0。")
            return 1
    o = _out(args.mode)
    res = client.call_business("calculate-price", {
        "storeCode": args.store, "orderType": 1, "beType": args.be_type,
        "needTableware": False, "items": items,
    })
    data = res.get("data") if isinstance(res, dict) else None
    if not isinstance(data, dict):
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    price = data.get("price")
    if not price:
        print("错误：核价返回 0。这通常意味着 items 结构有误（字段必须是 productCode），"
              "本工具拒绝把它当作「免费」。")
        return 1
    o.step("官方核价结果。")
    o.note(f"应付金额：{money(args.mode, price)}")
    if data.get("discount"):
        o.note(f"优惠：{money(args.mode, data['discount'])}")
    print(o.text())
    return 0


def cmd_order(args) -> int:
    """唯一会产生真实副作用的命令。必须 --confirm。"""
    if not args.confirm:
        print("已取消。order 会产生真实订单，必须显式加 --confirm。")
        return 1
    print("出于安全考虑，本版本不执行自动下单。")
    print("请用 quote 取得核价结果后，在麦当劳官方渠道完成支付。")
    print("原因：MCP 的 create-order 只返回支付链接，无法代付；"
          "自动下单存在误操作风险。")
    return 0


# --------------------------------------------------------------------------
# 命令：demo
# --------------------------------------------------------------------------

def cmd_demo(args) -> int:
    o = _out(args.mode)
    meta = demo_data.snapshot_meta()
    o.boundary(demo_data.DEMO_BANNER)
    o.blank()

    nutrition = demo_data.load_nutrition()
    menu = demo_data.demo_menu(limit=60)
    links = link_menu_nutrition(menu, nutrition)
    profile = get_profile("sodium")
    limit = profile.per_meal()

    o.step(f"营养快照共 {len(nutrition)} 条，来自官方 MCP 工具 list-nutrition-foods。")
    o.step(f"当前档位，限钠。日限额 2000 毫克，本餐额度 {limit:g} 毫克（按三分之一折算，工程假设）。")
    o.blank()

    verdicts = [evaluate(lk, profile.key, limit, profile.field) for lk in links]
    verdicts.sort(key=lambda v: (
        {"pass": 0, "over": 1, "unknown": 2}[v.status],
        v.value if v.value is not None else 10 ** 9,
    ))
    meal, light = _split_meal_and_light(verdicts, args.min_kcal)

    def _line(v, tail):
        n = v.link.nutrition
        txt = (f"{v.link.menu_item.name}。"
               f"能量 {unit(args.mode, n.energy_kcal, '千卡', 'kcal')}。"
               f"钠 {unit(args.mode, n.sodium_mg, '毫克', 'mg')}。")
        if n.sodium_density is not None:
            txt += f"钠密度每百千卡 {unit(args.mode, n.sodium_density, '毫克', 'mg')}。"
        return txt + tail

    page = 3 if args.mode == "large-print" else 5
    o.step("这一餐可以选的餐食（钠由低到高）。")
    passed_meal = [x for x in meal if x.status == "pass"][:page]
    for i, v in enumerate(passed_meal, 1):
        o.item(i, _line(v, "可以选"), total=len(passed_meal))
        if args.mode == "large-print":
            o.blank()
    if not passed_meal:
        o.boundary("在当前额度下没有可用的餐食，建议提高额度或改用其他档位。")

    o.blank()
    o.step("甜品与饮品（不计入主餐建议）。")
    passed_light = [x for x in light if x.status == "pass"][: page]
    for i, v in enumerate(passed_light, 1):
        o.item(i, _line(v, "可以选"), total=len(passed_light))
        if args.mode == "large-print":
            o.blank()

    o.blank()
    o.step("钠含量最高的几项（不建议）。")
    over = [x for x in meal if x.status == "over"][-3:]
    for i, v in enumerate(over, 1):
        n = v.link.nutrition
        o.item(i, f"{v.link.menu_item.name}。"
                  f"能量 {unit(args.mode, n.energy_kcal, '千卡', 'kcal')}。"
                  f"钠 {unit(args.mode, n.sodium_mg, '毫克', 'mg')}。"
                  f"超出本餐额度 {unit(args.mode, v.over_by, '毫克', 'mg')}。不建议",
               total=len(over))

    o.blank()
    matched = sum(1 for v in verdicts if v.link.nutrition is not None)
    o.boundary(f"本次匹配到营养数据的餐品 {matched} 项，未匹配 {len(verdicts) - matched} 项。")
    o.boundary(SODIUM_HINT_DISCLAIMER)

    if meta:
        o.blank()
        o.note(f"快照来源：{meta.get('source')}（{meta.get('captured_at')}）")

    o.blank()
    o.note("接入真实 MCP：export MCD_MCP_TOKEN=你的Token，然后在仓库根目录运行 "
           "python3 -m mcd_a11y plan --city 城市 --keyword 地点 --profile sodium"
           "（或用 ./scripts/mcd-a11y plan ...，免 cd）")
    print(o.text())
    return 0


# --------------------------------------------------------------------------
# 参数解析
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=APP,
        description="麦麦读得到 · 麦当劳无障碍点餐助手（零第三方依赖）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # 公共参数挂在每个子命令上，这样 `--mode` 写在子命令前后都能用
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mode", default="plain", choices=list(render.MODES),
                        help="输出模式：screen-reader 读屏友好 / large-print 大字 / plain 普通")

    sp = sub.add_parser("demo", parents=[common], help="离线演示，无需 Token")
    sp.add_argument("--min-kcal", type=float, default=60,
                    help="计入主餐建议的最低能量，低于此值归入甜品饮品")
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("profiles", parents=[common], help="列出饮食档位与阈值溯源")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_profiles)

    sp = sub.add_parser("stores", parents=[common], help="查询门店（营业中优先 + 距离升序）")
    sp.add_argument("--city"), sp.add_argument("--keyword")
    sp.add_argument("--be-type", type=int, default=1)
    sp.add_argument("--open-now", action="store_true", default=True)
    sp.add_argument("--demo", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_stores)

    sp = sub.add_parser("plan", parents=[common], help="主命令：按档位筛选可吃的餐品")
    sp.add_argument("--city"), sp.add_argument("--keyword")
    sp.add_argument("--be-type", type=int, default=1)
    sp.add_argument("--profile", default="sodium", choices=list(PROFILES))
    sp.add_argument("--sodium-cap", type=float, help="覆盖本餐钠额度（毫克）")
    sp.add_argument("--meal-kcal", type=float, help="本餐能量目标（推导控糖/低脂档位）")
    sp.add_argument("--top", type=int, default=5)
    sp.add_argument("--scan", type=int, default=60, help="演示模式下扫描的餐品数")
    sp.add_argument("--min-kcal", type=float, default=60,
                    help="计入主餐建议的最低能量，低于此值归入甜品饮品")
    sp.add_argument("--demo", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("tweak", parents=[common], help="特制清单（价格影响 + 方向性钠提示）")
    sp.add_argument("--store"), sp.add_argument("--code")
    sp.add_argument("--be-type", type=int, default=1)
    sp.add_argument("--demo", action="store_true")
    sp.set_defaults(func=cmd_tweak)

    sp = sub.add_parser("quote", parents=[common], help="官方核价（金额单位：分）")
    sp.add_argument("--store", required=True)
    sp.add_argument("--items", required=True, help='JSON，如 \'[{"productCode":"x","quantity":1}]\'')
    sp.add_argument("--be-type", type=int, default=1)
    sp.set_defaults(func=cmd_quote)

    sp = sub.add_parser("order", parents=[common], help="下单（必须 --confirm）")
    sp.add_argument("--quote", dest="quote_file")
    sp.add_argument("--confirm", action="store_true")
    sp.set_defaults(func=cmd_order)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except McpError as e:
        print(f"MCP 调用失败：{e.human()}", file=sys.stderr)
        return 2
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
