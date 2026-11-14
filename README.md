# nsc-benchmark

NuScale 17×17 燃料组件的单栅元（pin cell）临界基准，是整个 NuScale 堆芯仿真项目的第 1 步。

目标不是复现某个特定循环的临界硼浓度，而是先把**参数表 → 几何/材料 → 输运 → 结果 JSON → 图**这条链搭好，后续组件、堆芯、燃耗、热工共用同一套约定。

## 模型定义

方形栅元，四周反射边界，因此计算量是 `k_inf`。

| 参数 | 值 | 来源/说明 |
|---|---|---|
| 栅距 | 1.25984 cm | 0.496 in（NuScale DCA） |
| 燃料芯块半径 | 0.405765 cm | 直径 0.3195 in |
| 包壳内/外半径 | 0.41402 / 0.47498 cm | 0.326 / 0.374 in |
| U-235 富集度 | 3.1 wt% | DCA 组件中的最高富集度 |
| UO₂ 密度 | 10.4 g/cm³ | 约 95% 理论密度 |
| 包壳 | Zr-4（Zr 98.2 / Sn 1.5 / Fe 0.2 / Cr 0.1 wt%） | 简化无杂质 |
| 慢化剂 | 轻水 0.998 g/cm³，294 K | 含 `c_H_in_H2O` 热散射 |
| 硼 | 0–2000 ppm（自然硼，按重量） | 以原子密度加入水 |
| 统计 | 20000 粒子/代 × 120 代（前 30 代弃） | σ(k) ≈ 20 pcm |

## 目录

```
params/nuscale_pin.json   单栅元参数表（第 1 步唯一输入）
params/nuscale_core.json  组件/堆芯/模块的 CAD 参数表（来自 ecp-benchmarks）
nsc_bench/model.py        材料与几何构建
nsc_bench/cad.py          CadQuery 四级实体模型
nsc_bench/core.py         37 组件 2D OpenMC 堆芯（每组件独立水材料）
scripts/sweep_boron.py    硼浓度扫描 → results/boron_sweep.json
scripts/plot_kinf.py      画 k_inf 曲线 → results/kinf_vs_boron.{png,svg}
scripts/build_cad.py      导出 STEP/STL/HTML → results/cad/
scripts/run_core.py       堆芯 k_eff + 每组件功率 → power.json
scripts/build_foam_case.py 功率 → 2D 轴对称自然循环 OpenFOAM 案例
scripts/run_foam_wsl.sh   WSL 中求解 OpenFOAM（复制到无空格路径）
scripts/foam_post.py      环带温度 → IAPWS 水密度 → densities.json
scripts/couple.py         OpenMC ↔ OpenFOAM 迭代 → results/coupling/
scripts/render_cad_blender.py Blender 渲染 CAD（后台模式）
scripts/make_figures.py   CFD 场图、GIF、三维剖切 → results/figures/
scripts/make_gallery.py   生成 results/figures/index.html
docs/cad_cae.md           CAD 与 OpenMC/OpenFOAM 的接口结论
results/                  结果（cases/ 下是每个硼浓度的 OpenMC 输入与状态点）
results/figures/          CAD 渲染与 CFD 图集
```

约定：脚本只读 `params/`，结果只写 `results/`，物理模型不写任何绘图逻辑。

## 运行

需要 OpenMC（编译了 DAGMC 与否均可）与 HDF5 截面库：

```bash
export OPENMC_CROSS_SECTIONS=/path/to/cross_sections.xml
python -m scripts.sweep_boron          # 加 --force 重跑已有算例
python scripts/plot_kinf.py
```

截面库只有 294 K 数据时，模型按冷态（CZP）自洽计算；要算热态需要在参数表里改
`temperature_K` 与 `water_density_g_cm3`，并准备 600 K 的 HDF5 库（`openmc.data` 或
NJOY 生成），否则 OpenMC 会拒绝运行。

## 结果

旧的 4.95 wt% 结果归档在 `results/archive_4p95/`。参数表已切到 NuScale DCA 几何（3.1 wt%），需要用 OpenMC 重跑：

```bash
python -m scripts.sweep_boron
python scripts/plot_kinf.py
```

## CAD 模型（第 1.5 步）

按 `mit-crpg/ecp-benchmarks` 的 NuScale-like SMR 尺寸反推的四级 BRep 模型，尺寸全部来自 `params/nuscale_core.json`：

| LOD | 内容 | 用途 |
|---|---|---|
| `pin` | 芯块 + 包壳 | 单栅元/单通道对照 |
| `assembly` | 17×17、264 根燃料棒、24 导向管、5 层格架、上下管座 | 组件级中子学/CFD |
| `core` | 37 组件（1.6/2.4/3.1 wt%）、重反射层、吊篮、下降段、RPV | 堆芯级中子学 |
| `module` | RPV + 钢制安全壳 CNV（Ø4.57 m × 23.16 m） | 自然循环系统分析 |

```bash
python scripts/build_cad.py        # STEP + STL + 三维 HTML + manifest
```

产物在 `results/cad/`，`manifest.json` 记录体积、包围盒和解析校验（全部通过）。单位、基准面、DAGMC/OpenFOAM 转换约定见 [docs/cad_cae.md](docs/cad_cae.md)。

## OpenMC ↔ OpenFOAM 耦合（第 3 步）

37 组件 2D OpenMC 堆芯（`results/core/power.json`）与 5° 轴对称自然循环 CFD 双向迭代：OpenMC 每组件功率 → 4 个径向环热源；CFD 环带温度 → 15.5 MPa 水密度（IAPWS-IF97）→ OpenMC 每组件水材料。

```bash
python scripts/couple.py --iterations 3 --start-iteration 0
```

| 迭代 | k_eff | Δk | 环带密度 / g·cm⁻³（内→外） | 堆芯 / 下降段轴向速度 |
|---|---|---|---|---|
| 0（冷态） | 1.25135 ± 0.00512 | — | 0.761 / 0.757 / 0.753 / 0.746 | — |
| 1 | 1.22297 ± 0.00232 | 0.0284 | 0.753 / 0.749 / 0.752 / 0.751 | +0.81 / −0.92 m/s |
| 2 | 1.22409 ± 0.00205 | 0.0011 | 0.749 / 0.746 / 0.751 / 0.749 | +0.80 / −0.92 m/s |

温度场 540–578 K，下降段 547–550 K；`Δk` 已进入 1σ。这轮用的是固定体积热阱 + 拍值的多孔阻力。

**SG 线性换热器 + 40 kPa 占位压降（本轮）。** SG 区改为 `scalarSemiImplicitSource`，`q''' = k(T_sec − T)`，`k = ln[(T_in−T_sec)/(T_out−T_sec)]/τ = 0.13420 1/s`（`T_sec=505 K`、`T_in/T_out=570/543 K`、`τ=4 s`）；堆芯与 SG 多孔阻力按 `ΔP=(ρ/2)fLu²` 反解，取 37 组件 40 kPa @ 4 m/s（按面积比 3.05 折成表观速度 1.311 m/s）得 `f=28.20`，SG 取 20 kPa 得 `f=4.404`。全部数值在 `params/nuscale_core.json` 的 `thermal_hydraulics` 块。

验证（`results/coupling/hx_validation.json`，t = 130 s）：

| 量 | 值 |
|---|---|
| 堆芯 / 下降段轴向速度 | +0.245 / −0.344 m/s |
| 温度范围 | 521.4–620.0 K |
| SG 进口 / 出口 | 572.2 / 524.2 K |
| SG 热负荷 vs 堆芯功率 | 2.210 MW vs 2.222 MW（不平衡 0.53%） |
| 热态 k_eff | 1.21946 ± 0.00223 |

能量不平衡从 t=0 的 36.7% 降到 0.53%，中途在 0.2–4% 间低频振荡（自然循环回路的密度波振荡）。`summary.json` 仍是旧模型的三轮结果，完整耦合需用新模型重跑。CFD 拓扑、标定推导与已知缺口见 [docs/cad_cae.md](docs/cad_cae.md) 第 11 节。

## 图集（CAD 渲染 + CFD 结果）

`results/figures/index.html` 汇总所有可视化：CadQuery 生成的 pin/assembly/core/module 四级模型（Blender 渲染，含剖切）与 5° wedge 的温度场、轴向速度场、能量平衡历史、13 帧温度动画和 CFD 计算域三维剖切。

```bash
blender -b -P scripts/render_cad_blender.py -- --root . --out results/figures
python scripts/make_figures.py     # CFD 场图、GIF、三维剖切
python scripts/make_gallery.py     # 生成 index.html
```

## 已知局限

- 单栅元 + 反射边界，缺少组件内相邻棒、导向管、反射层的谱效应，结果只用于验证建模链与硼价值量级。
- 294 K 截面 + 冷态水密度：没有多普勒与慢化剂温度反馈，不能替代热态临界计算。
- 包壳用四种元素的均匀混合物，未含杂质与氧化层。
- 燃耗、Gd 可燃毒物、控制棒在后续步骤加入。

## 路线图

| 步 | 内容 | 通过标准 |
|---|---|---|
| 1 | 单栅元 + 硼扫描（本仓库） | k_inf 曲线单调、硼价值量级合理、临界硼可插值 |
| 1.5 | 四级 CAD + CAE 接口 | STEP 可重导入、体积校验通过、单位/基准面写清 |
| 2 | 17×17 组件（导向管、Gd 棒） | k_inf vs 硼，功率峰因子 |
| 3 | 37 组件 2D 堆芯 + 反射层 | 径向功率分布（冷态与热态密度均已跑通） |
| 4 | 燃耗（若干循环步） | 燃耗深度、Gd 耗尽、循环长度 |
| 5 | OpenMC ↔ OpenFOAM 水密度反馈 | k_eff 与环带密度收敛（首轮完成；SG 换热器 + 40 kPa 压降标定已跑通，待重跑完整耦合） |
