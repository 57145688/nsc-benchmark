"""Write the figure gallery (results/figures/index.html).

Numbers come from ``results/coupling/hx_validation.json`` so the captions stay
in sync with the latest re-run.  The gallery only references files next to it,
so it can be opened directly from disk.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGURES = os.path.join(HERE, "results", "figures")
VALIDATION = os.path.join(HERE, "results", "coupling", "hx_validation.json")
COLD = os.path.join(HERE, "results", "coupling", "iter0", "power.json")
HOT = os.path.join(HERE, "results", "coupling", "hx_hot", "power.json")

CAD = [
    ("cad_pin.png", "燃料棒（pin）", "单棒 LOD：包壳 + 芯块，全长 216 cm、外径 0.95 cm。"),
    ("cad_pin_section.png", "燃料棒剖面", "切开近侧的一半，看芯块与包壳的径向分层。"),
    ("cad_assembly.png", "17×17 组件", "264 根燃料棒、24 根导向管、5 层格架、上下管座。"),
    ("cad_assembly_section.png", "组件局部", "格架与棒束的轴向细节。"),
    ("cad_core.png", "37 组件堆芯（俯视）", "堆芯围板、反射层与 37 个组件端面。"),
    ("cad_core_section.png", "堆芯剖面", "切开 RPV/围板，看组件区与下降段环形通道。"),
    ("cad_module.png", "SMR 模块外形", "钢制安全壳 CNV，Ø4.57 m × 23.16 m。"),
    ("cad_module_section.png", "模块剖面", "CNV 内部的 RPV 与堆芯，两者独立薄壁。"),
]

CFD = [
    ("cfd_temperature.png", "冷却剂温度场", "5° 轴对称 wedge，{t} s；堆芯加热、环隙蒸汽发生器冷却。"),
    ("cfd_velocity.png", "轴向速度与流向", "红色向上（堆芯、上升段），蓝色向下（SG、下降段）。"),
    ("cfd_energy_balance.png", "能量平衡历史", "SG 热负荷与堆芯功率随时间的变化及不平衡率。"),
    ("cfd_temperature.gif", "温度场动画", "从 {first} s 到 {t} s 的准稳态演化。"),
    ("cfd_domain_3d.png", "CFD 计算域（三维剖切）", "多孔堆芯、上升段、环形 SG、下降段与吊篮。"),
]

OPENMC = [
    (
        "openmc_core_power.png",
        "37 组件功率分布",
        "左：初始水密度（0.998 g/cm³）；右：CFD 热态反馈。数字为组件功率/堆芯平均，下方为富集度。",
    ),
    (
        "openmc_keff_rings.png",
        "k_eff 与径向功率份额",
        "冷态 {k_cold}、热态 {k_hot}，Δk = {dk}；热态中心组件功率峰值 {peak}× 堆芯平均。",
    ),
]

TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>NuScale-like SMR — CAD 与 CAE 图集</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{
    margin: 0; padding: 40px 6vw 80px;
    background: #0b0e12; color: #dbe3ec;
    font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  }}
  h1 {{ font-size: 28px; font-weight: 600; margin: 0 0 6px; }}
  h2 {{ font-size: 19px; margin: 48px 0 14px; color: #8fb8de; }}
  p.lead {{ color: #93a1b1; margin: 0 0 8px; max-width: 70ch; line-height: 1.6; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 18px; }}
  figure {{ margin: 0; background: #131920; border: 1px solid #1f2933; border-radius: 10px; overflow: hidden; }}
  figure a {{ display: block; }}
  img {{ display: block; width: 100%; height: auto; background: #0f141a; }}
  figcaption {{ padding: 10px 12px 12px; font-size: 13px; line-height: 1.55; color: #9fb0c2; }}
  figcaption b {{ display: block; color: #e6edf5; font-size: 14px; margin-bottom: 3px; font-weight: 600; }}
  .facts {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; margin: 18px 0 0; }}
  .fact {{ background: #131920; border: 1px solid #1f2933; border-radius: 10px; padding: 12px 14px; }}
  .fact span {{ display: block; font-size: 12px; color: #7f8fa3; }}
  .fact strong {{ display: block; font-size: 19px; margin-top: 4px; color: #e6edf5; font-weight: 600; }}
  .links {{ margin-top: 10px; font-size: 13px; color: #93a1b1; }}
  .links a {{ color: #8fb8de; text-decoration: none; margin-right: 14px; }}
  .links a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>NuScale-like SMR — CAD 与 CAE 图集</h1>
<p class="lead">原始几何来自 <code>params/nuscale_core.json</code>（ecp-benchmarks 尺寸），
CAD 用 CadQuery 生成 STEP/STL，再用 Blender 渲染；CFD 是 5° 轴对称自然循环模型，
由 OpenMC 径向功率驱动。图中温度为 15.5 MPa 液态水。</p>

<div class="facts">
  <div class="fact"><span>热态 k_eff</span><strong>{k_eff} ± {k_sigma}</strong></div>
  <div class="fact"><span>堆芯 / 下降段轴向速度</span><strong>{core_u} / {down_u} m/s</strong></div>
  <div class="fact"><span>SG 进口 / 出口</span><strong>{sg_in} / {sg_out} K</strong></div>
  <div class="fact"><span>SG 热负荷</span><strong>{duty} MW</strong></div>
  <div class="fact"><span>能量不平衡</span><strong>{imbalance}%</strong></div>
  <div class="fact"><span>k_eff 冷态 → 热态</span><strong>{k_cold} → {k_hot}</strong></div>
  <div class="fact"><span>热态径向功率峰值</span><strong>{peak}× 平均</strong></div>
</div>

<h2>OpenMC 中子学（37 组件 2D 堆芯）</h2>
<div class="links">
  <a href="../coupling/iter0/power.json">冷态 power.json</a>
  <a href="../coupling/hx_densities.json">反馈密度</a>
  <a href="../coupling/hx_hot/power.json">热态 power.json</a>
</div>
<div class="grid">
{openmc}
</div>

<h2>CAD 模型（Blender 渲染）</h2>
<div class="links">
  <a href="../cad/nuscale_pin.html">pin 交互视图</a>
  <a href="../cad/nuscale_assembly.html">assembly 交互视图</a>
  <a href="../cad/nuscale_core.html">core 交互视图</a>
  <a href="../cad/nuscale_module.html">module 交互视图</a>
</div>
<div class="grid">
{cad}
</div>

<h2>CFD 结果</h2>
<div class="grid">
{cfd}
</div>
</body>
</html>
"""

CARD = """  <figure>
    <a href="{src}"><img src="{src}" alt="{title}" loading="lazy"></a>
    <figcaption><b>{title}</b>{caption}</figcaption>
  </figure>"""


def main():
    with open(VALIDATION) as handle:
        validation = json.load(handle)
    with open(COLD) as handle:
        cold = json.load(handle)
    with open(HOT) as handle:
        hot = json.load(handle)
    peak = max(item["power_fraction"] for item in hot["assemblies"]) * len(
        hot["assemblies"]
    )
    field = validation["field"]
    times = []
    case = os.path.join(HERE, "results", "foam", "case")
    for name in os.listdir(case):
        try:
            number = float(name)
        except ValueError:
            continue
        if number > 0:
            times.append(number)

    values = {
        "k_eff": f"{validation['hot_k_eff']:.5f}",
        "k_sigma": f"{validation['hot_k_sigma']:.5f}",
        "core_u": f"{field['core_mean_velocity_z_m_s']:+.3f}",
        "down_u": f"{field['downcomer_mean_velocity_z_m_s']:+.3f}",
        "sg_in": f"{field['sg_inlet_temperature_K']:.1f}",
        "sg_out": f"{field['sg_outlet_temperature_K']:.1f}",
        "duty": f"{field['sg_duty_W'] / 1e6:.3f}",
        "imbalance": f"{100 * field['energy_imbalance']:.2f}",
        "t": f"{max(times):.1f}",
        "first": f"{min(times):.0f}",
        "k_cold": f"{cold['k_eff']:.5f}",
        "k_hot": f"{hot['k_eff']:.5f}",
        "dk": f"{cold['k_eff'] - hot['k_eff']:.4f}",
        "peak": f"{peak:.2f}",
    }
    cad_cards = "\n".join(
        CARD.format(src=src, title=title, caption=caption) for src, title, caption in CAD
    )
    openmc_cards = "\n".join(
        CARD.format(src=src, title=title, caption=caption.format(**values))
        for src, title, caption in OPENMC
    )
    cfd_cards = "\n".join(
        CARD.format(src=src, title=title, caption=caption.format(**values))
        for src, title, caption in CFD
    )
    html = TEMPLATE.format(cad=cad_cards, cfd=cfd_cards, openmc=openmc_cards, **values)
    path = os.path.join(FIGURES, "index.html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
