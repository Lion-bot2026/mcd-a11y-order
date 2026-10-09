# -*- coding: utf-8 -*-
"""慢病饮食档位。

设计原则：**宁缺毋编**。
每个档位必须写明权威口径与出处；查不到确切出处的，verified=False 并在输出中标注
「需人工核实」；存在医疗误用风险的档位（如低蛋白）直接不做。

单餐额度一律标注为「工程假设」，可用命令行参数覆盖，绝不包装成权威标准。
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Profile", "PROFILES", "get_profile", "MEAL_SHARE_DEFAULT"]

# 默认按餐次均分。**这是工程假设，不是权威口径**，输出中必须显式说明可覆盖。
MEAL_SHARE_DEFAULT = 1.0 / 3.0


@dataclass
class Profile:
    key: str
    label: str
    field: str                 # 对应 NutritionItem 的字段名
    unit_cn: str               # 读屏模式用的中文单位
    unit_sym: str              # 普通模式用的符号单位
    daily_limit: float | None  # 日限额；None = 需按能量目标推导
    daily_basis: str           # 权威口径原文
    source: str                # 溯源
    verified: bool             # False = 输出中标注「需人工核实」
    value_cn: str = ""         # 数值名称，如「钠」「碳水」，用于「钠 250 毫克」这类表述
    caveats: tuple[str, ...] = field(default=())

    def per_meal(self, meal_share: float = MEAL_SHARE_DEFAULT,
                 meal_kcal: float | None = None) -> float | None:
        """推导单餐上限。推导不出来的返回 None，由调用方跳过该项检查。"""
        raise NotImplementedError


@dataclass
class FixedProfile(Profile):
    """日限额固定，单餐按餐次占比折算。"""

    def per_meal(self, meal_share: float = MEAL_SHARE_DEFAULT,
                 meal_kcal: float | None = None) -> float | None:
        if self.daily_limit is None:
            return None
        return round(self.daily_limit * meal_share, 1)


@dataclass
class EnergyDerivedProfile(Profile):
    """按供能比推导：克数 = 单餐能量目标 × 供能比 ÷ 每克供能。"""

    ratio: float = 0.0          # 供能比上限
    kcal_per_gram: float = 0.0  # 每克该营养素供能

    def per_meal(self, meal_share: float = MEAL_SHARE_DEFAULT,
                 meal_kcal: float | None = None) -> float | None:
        if meal_kcal is None or self.ratio <= 0 or self.kcal_per_gram <= 0:
            return None
        return round(meal_kcal * self.ratio / self.kcal_per_gram, 1)


@dataclass
class UserProfile(Profile):
    """完全由用户自填，无默认值。控能量档：本餐能量目标即本餐额度。"""

    def per_meal(self, meal_share: float = MEAL_SHARE_DEFAULT,
                 meal_kcal: float | None = None) -> float | None:
        # 能量档不做任何换算 —— 额度就是用户自己给的这一餐能量目标。
        # 缺目标时返回 None，由调用方给出可操作提示。
        if not meal_kcal or meal_kcal <= 0:
            return None
        return float(meal_kcal)


PROFILES: dict[str, Profile] = {
    "sodium": FixedProfile(
        key="sodium",
        label="限钠",
        field="sodium_mg",
        unit_cn="毫克",
        unit_sym="mg",
        value_cn="钠",
        daily_limit=2000.0,
        daily_basis="成人每日钠摄入低于 2000 毫克（约合食盐 5 克）",
        source="WHO《Sodium intake for adults and children》(2012)",
        verified=True,
    ),
    "carb": EnergyDerivedProfile(
        key="carb",
        label="控糖",
        field="carb_g",
        unit_cn="克",
        unit_sym="g",
        value_cn="碳水",
        daily_limit=None,
        daily_basis="游离糖供能低于总能量的 10%（建议进一步低于 5%）",
        source="WHO《Guideline: sugars intake for adults and children》(2015)",
        verified=True,
        ratio=0.10,
        kcal_per_gram=4.0,
        caveats=(
            "麦当劳 MCP 只提供「碳水化合物」总量，不区分游离糖。",
            "本档位以总碳水化合物作为代理指标套用 WHO 游离糖口径 —— "
            "总碳水 ≥ 游离糖，因此判定结果偏严格（保守），不会漏放过线餐品。",
        ),
    ),
    "fat": EnergyDerivedProfile(
        key="fat",
        label="低脂",
        field="fat_g",
        unit_cn="克",
        unit_sym="g",
        value_cn="脂肪",
        daily_limit=None,
        daily_basis="脂肪供能比 20%–30%",
        source="《中国居民膳食指南（2022）》",
        verified=False,  # 原文页码待人工核实
        ratio=0.30,
        kcal_per_gram=9.0,
        caveats=("供能比取值待人工核实原文出处，请勿作为临床依据。",),
    ),
    "energy": UserProfile(
        key="energy",
        label="控能量",
        field="energy_kcal",
        unit_cn="千卡",
        unit_sym="kcal",
        value_cn="能量",
        daily_limit=None,
        daily_basis="由使用者自行指定本餐能量目标",
        source="用户自填，无外部权威口径",
        # 标False 而不是 True：没有外部权威口径，就不能说「已核实」。
        # 底层的核查动作由用户自己完成。
        verified=False,
        caveats=("本档位无外部权威口径，额度完全由用户自填，不构成营养建议。",),
    ),
}

# 明确不做：低蛋白档位。CKD 蛋白质限量按体重与分期个体化（g/kg/d），
# 给固定克数存在误导肾病患者的风险，属于本项目主动放弃的高风险能力。
EXCLUDED_NOTE = (
    "本项目不提供「低蛋白」档位。慢性肾脏病的蛋白质摄入需按体重与分期个体化"
    "确定（g/kg/d），固定克数存在误导风险。有此需求请咨询临床营养师。"
)


def get_profile(key: str) -> Profile:
    try:
        return PROFILES[key]
    except KeyError:
        raise SystemExit(f"未知档位：{key}。可选：{', '.join(PROFILES)}")


def describe_profiles() -> list[dict]:
    """供 `profiles` 命令输出，含溯源与核实状态。

    「日限额数值」与「单位」分开给出，让调用方能按输出模式选
    中文单位（读屏）或符号单位 —— 否则读屏模式会念出「2000 mg」。
    """
    rows = []
    for p in PROFILES.values():
        rows.append({
            "档位": p.key,
            "名称": p.label,
            "日限额数值": (f"{p.daily_limit:g}" if p.daily_limit else ""),
            "单位中文": p.unit_cn,
            "单位符号": p.unit_sym,
            "日限额": (f"{p.daily_limit:g} {p.unit_sym}" if p.daily_limit else "按能量目标推导"),
            "权威口径": p.daily_basis,
            "溯源": p.source,
            "已核实": "是" if p.verified else "否（需人工核实）",
            # caveats 各条自带句号，直接用「；」连接会拼出「。；」
            "数据边界": "；".join(c.rstrip("。") for c in p.caveats) if p.caveats else "",
        })
    return rows
