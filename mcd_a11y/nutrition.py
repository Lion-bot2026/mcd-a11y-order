# -*- coding: utf-8 -*-
"""营养数据模型、跨表匹配与阈值判定。

两条铁律：
  1. 缺失值 = None，绝不当 0。当 0 会误判「低钠」从而放过整类餐品。
  2. 未匹配到的餐品 = 「未评估」，既不当合格也不当不合格。
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .parser import coerce_scalar, normalize_name

__all__ = ["NutritionItem", "MenuItem", "MatchLink", "from_toon_rows",
           "link_menu_nutrition", "evaluate", "Verdict"]

MATCH_TYPES = ("exact", "normalized", "token", "fuzzy", "unmatched")


@dataclass
class NutritionItem:
    product_name: str
    energy_kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    carb_g: float | None = None
    sodium_mg: float | None = None
    calcium_mg: float | None = None

    @property
    def sodium_density(self) -> float | None:
        """每 100 千卡的钠毫克数 —— 跨品类可比，避免「低热量所以低钠」的错觉。"""
        if self.sodium_mg is None or not self.energy_kcal:
            return None
        return round(self.sodium_mg / self.energy_kcal * 100, 1)

    def get(self, field_name: str) -> float | None:
        return getattr(self, field_name, None)


@dataclass
class MenuItem:
    """门店在售餐品。价格单位是「元」（query-meals 返回字符串元）。"""

    code: str
    name: str
    category: str | None = None
    current_price_yuan: float | None = None
    original_price_yuan: float | None = None
    store_code: str | None = None
    daypart: str | None = None

    @property
    def price_cents(self) -> int | None:
        if self.current_price_yuan is None:
            return None
        return int(round(self.current_price_yuan * 100))


@dataclass
class MatchLink:
    menu_item: MenuItem
    nutrition: NutritionItem | None
    match_type: str          # exact / normalized / token / fuzzy / unmatched
    confidence: float


_FIELD_MAP = {
    "productName": "product_name",
    "energyKcal": "energy_kcal",
    "energyKJ": "energy_kcal",
    "energyKj": "energy_kcal",
    "protein": "protein_g",
    "fat": "fat_g",
    "carbohydrate": "carb_g",
    "sodium": "sodium_mg",
    "calcium": "calcium_mg",
}


def from_toon_rows(rows: Iterable[dict]) -> list[NutritionItem]:
    """把 TOON 解析出的行列表转成 NutritionItem。字段名按别名表映射，缺字段跳过。"""
    items: list[NutritionItem] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        name = r.get("productName") or r.get("product_name")
        if not name:
            continue
        data: dict[str, Any] = {"product_name": str(name).strip()}
        for src, dst in _FIELD_MAP.items():
            if dst in data and data[dst] is not None:
                continue
            v = coerce_scalar(r.get(src))
            if isinstance(v, (int, float)):
                data[dst] = float(v)
        items.append(NutritionItem(**data))
    return items


def link_menu_nutrition(menu: Sequence[MenuItem],
                        nutrition: Sequence[NutritionItem]) -> list[MatchLink]:
    """五层降级匹配。营养表不返回 productCode，只能按餐品名匹配。

    逐层降级，且匹配类型会暴露在输出里 —— 让用户知道这条结论有多可靠。
    """
    exact = {n.product_name.strip(): n for n in nutrition}
    norm = {}
    for n in nutrition:
        norm.setdefault(normalize_name(n.product_name), n)
    norm_keys = list(norm.keys())

    links: list[MatchLink] = []
    for m in menu:
        raw = m.name.strip()
        if raw in exact:
            links.append(MatchLink(m, exact[raw], "exact", 1.0))
            continue

        k = normalize_name(raw)
        if not k:
            links.append(MatchLink(m, None, "unmatched", 0.0))
            continue

        if k in norm:
            links.append(MatchLink(m, norm[k], "normalized", 0.95))
            continue

        # 双向子串包含，长度差不超过 2 —— 覆盖「巨无霸」vs「巨无霸套餐」这类差异，
        # 同时避免因「麦香鱼」包含于「麦香鱼堡」造成的过宽命中。
        hits = [norm[kk] for kk in norm_keys
                if (kk and (kk in k or k in kk)) and abs(len(kk) - len(k)) <= 2]
        if len(hits) == 1:
            links.append(MatchLink(m, hits[0], "token", 0.8))
            continue

        near = difflib.get_close_matches(k, norm_keys, n=1, cutoff=0.88)
        if near:
            links.append(MatchLink(m, norm[near[0]], "fuzzy", 0.6))
            continue

        links.append(MatchLink(m, None, "unmatched", 0.0))
    return links


@dataclass
class Verdict:
    link: MatchLink
    profile_key: str
    limit: float | None
    value: float | None
    status: str        # pass / over / unknown
    over_by: float | None = None
    reasons: tuple[str, ...] = field(default=())


def evaluate(link: MatchLink, profile_key: str, limit: float | None,
             field_name: str) -> Verdict:
    """单餐品单档位判定。

    status:
      pass    —— 有数据且未超额度
      over    —— 有数据且超额度
      unknown —— 数据缺失或未匹配；**绝不当 pass**
    """
    n = link.nutrition
    if n is None:
        return Verdict(link, profile_key, limit, None, "unknown",
                       reasons=("营养表未匹配到该餐品",))
    value = n.get(field_name)
    if value is None:
        return Verdict(link, profile_key, limit, None, "unknown",
                       reasons=(f"该餐品的{field_name}数据缺失",))
    if limit is None:
        return Verdict(link, profile_key, None, value, "unknown",
                       reasons=("未设定额度（需提供能量目标或单餐额度）",))
    if value > limit:
        return Verdict(link, profile_key, limit, value, "over",
                       over_by=round(value - limit, 1))
    return Verdict(link, profile_key, limit, value, "pass")
