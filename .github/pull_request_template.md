## 改了什么

<!-- 一句话说清动机 -->

## 涉及范围

- [ ] 播报文案与输出格式（`mcd_a11y/render.py`）
- [ ] 档位阈值与营养口径（`mcd_a11y/profiles.py` / `nutrition.py`）
- [ ] 菜单数据与解析（`mcd_a11y/menu.py` / `parser.py`）
- [ ] Skill 与文档（`SKILL.md` / `references/` / `README.md`）

## 自检

- [ ] `python3 -m unittest discover -s tests -v` 全部通过
- [ ] 若改了播报文案，`tests/test_docs_consistency.py` 仍通过（文档与实现不脱节）
- [ ] 若改了阈值或口径，`references/thresholds.md` 同步更新
- [ ] 措辞保持中性，不对餐品作评价（参赛合规要求）

## 备注

<!-- 取舍、未覆盖的边界 -->
