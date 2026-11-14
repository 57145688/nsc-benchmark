# NuScale-like SMR：CAD 与 CAE 交互结论

本文记录 `nsc-benchmark` 里 CAD 链路（CadQuery）与 CAE 链路（OpenMC / OpenFOAM）之间的接口约定。几何参数只有一份：`params/nuscale_core.json`，数值来自 `mit-crpg/ecp-benchmarks` 的 `smr/smr/surfaces.py`、`core.py`、`assemblies.py`（commit `db5c6bf`），外形包络来自 NuScale DCA 与公开白皮书。

## 1. 结论摘要

1. **CAD 与 CAE 必须共用一份参数表。** `params/nuscale_core.json` 同时驱动 `nsc_bench/cad.py`（BRep）和后续 OpenMC/OpenFOAM 输入。参数表里的尺寸、富集度、组件排布只要改一处，两侧同时变。
2. **必须按求解器分 LOD。** 单棒（`pin`）、组件（`assembly`）、堆芯（`core`）、模块（`module`）四级模型分别对应不同的 CAE 用途；把 37×289 根棒全部做成实体再去划 CFD 网格，既无必要也不可行。
3. **单位与基准面是最容易出错的地方。** CAD/STEP/STL 用 cm，OpenFOAM 用 m；CAD 的 `z=0` 定在下管座底面，比 ecp-benchmarks 的参考面高 6.6205 cm。跨工具传递时必须显式换算。
4. **NuScale 的几何特征已经被参数表固化。** 活性段 199.9996 cm（78.74 in，约为常规 PWR 365.76 cm 的一半）、无主泵、CNV 与 RPV 两层独立薄壁壳、37 组 17×17 组件。这些是后续 CFD 与中子学建模的硬约束。
5. **STEP 是 CAD↔CAE 的中性交换格式。** DAGMC 转换（`cad_to_dagmc` + gmsh + MOAB）和 OpenFOAM 网格化都应以 STEP 为输入；本机 Windows 环境没有这套工具链，转换应在 WSL/Linux 执行。
6. **当前 CAD 已达到"每个部件封闭、互不重叠、体积可解析校验"的状态**：`results/cad/manifest.json` 中所有检查通过，包壳与芯块体积和解析值的相对误差 < 1e-15，组件/堆芯/模块外形尺寸与参数表一致。

## 2. 参数与来源

| 项目 | 值（cm） | 说明 |
|---|---|---|
| 芯块直径 / 长度 | 0.81153 / 1.016 | 0.3195 in、0.4 in |
| 包壳内/外直径 | 0.82804 / 0.94996 | 0.326 / 0.374 in |
| 燃料棒长 / 活性段 | 215.9 / 199.9996 | 85 in / 78.74 in（半长燃料） |
| 棒距 | 1.25984 | 0.496 in |
| 组件 17×17 节距 | 21.50364 | 8.466 in |
| 组件高度 | 243.5606 | 95.89 in |
| 组件构成 | 264 燃料棒 + 24 导向管 + 1 仪表管 | 25 个非燃料位 |
| 堆芯 | 37 组件，9×9 排布 | 富集度 1.6 / 2.4 / 3.1 wt% |
| 吊篮内/外半径 | 93.98 / 99.06 | 74 / 78 in 直径 |
| RPV 内/外半径 | 122.555 / 133.35 | 96.5 / 105 in 直径 |
| CNV 直径 × 高 × 壁厚 | 457 × 2316 × 5 | 15 ft × 76 ft，公开包络 |

补充：

- RPV 高度取 1050 cm（公开资料约 10 m 量级），DCA 只给了直径，没有给全长。
- CNV 顶部/底部按 2:1 椭圆封头建模，封头深度 = 直径/4。
- 堆芯外围的重反射层在 ecp 模型里是带水孔的组件尺寸块；CAD 简化为 `82 → 93.98 cm` 的环形块，水孔未建模。
- ecp 的 `build-core-short.py` 把堆芯节距改成 `17 × pin_pitch = 21.41728 cm`，而 DCA 值是 8.466 in = 21.50364 cm。**CAD 用 DCA 值**，两者相差 0.4%；以后做堆芯级耦合时必须二选一并写进参数表。

## 3. 四级 LOD 与 CAE 映射

| LOD | 实体数 | 用途 | OpenMC | OpenFOAM |
|---|---|---|---|---|
| `pin` | 2 | 单栅元 `k_inf` 复核、单通道 CHF | 与 `model.py` 的 pin cell 对照 | 单通道共轭传热，边界层网格 |
| `assembly` | 296 | 组件级中子学、组件级 CFD | 17×17 lattice + 导向管 | 棒束通道；或整体作为多孔区 |
| `core` | 41 | 37 组件堆芯、功率分布 | 堆芯 lattice + 反射层 + 吊篮 | 堆芯作为多孔区，只保留吊篮/下降段 |
| `module` | 42 | 自然循环系统分析 | 不作为中子学输入 | RPV 内流体域 + CNV 外边界 |

产物（`python scripts/build_cad.py` 生成）：

```
results/cad/nuscale_{pin,assembly,core,module}.step   实体，STEP 声明单位 cm
results/cad/nuscale_{pin,assembly,core,module}.stl    无单位，按 cm 解释
results/cad/nuscale_{pin,assembly,core,module}.html   Plotly 三维视图
results/cad/manifest.json                             体积/包围盒/校验项
```

## 4. 坐标、单位与基准

- **CAD**：`z=0` = 下管座底面，`z=243.5606` = 上管座顶面；活性段 `21.7805 → 221.7801`。
- **ecp OpenMC**：`bottom_lower_nozzle = -6.6205`，`bottom_fuel_stack = 15.16`，`top_active_core = 215.16`。换算关系：`z_CAD = z_ecp + 6.6205`。
- **STEP**：文件头声明 `SI_UNIT(.CENTI.,.METRE.)`。注意 CadQuery/OCCT 的 STEP 读取器会归一化到 mm（实测重导入后坐标 ×10），所以任何"读到 mm"的链路都要再 ×0.1 才能对得上 OpenMC 的 cm。
- **OpenFOAM**：`transformPoints -scale '(0.01 0.01 0.01)'`，或在 `snappyHexMesh` 的 `geometry` 段用 `scale 0.01`。
- **STL**：无单位，按 cm 解释；不要直接丢给默认 mm 的 CFD 前处理器。

## 5. CAD → OpenMC / DAGMC

参照 paramak 的做法，实际链路是：

```
参数表 → CadQuery BRep → STEP → cad_to_dagmc → DAGMC .h5m → OpenMC
```

关键约定：

1. **每种材料一个封闭体**：燃料芯块、包壳、导向管、冷却剂、不锈钢结构各自独立；DAGMC 不接受互相穿插的实体。
2. **外部水/真空用 implicit complement**：CAD 里不显式画"整个水池"，由 `cad_to_dagmc(..., implicit_complement=True)` 生成；这与 paramak 导出聚变堆真空室外部区域的处理一致。
3. **显式缝合边**：paramak 用两个 180° 旋转再 union，避免周期性曲面无法网格化；本项目的封头是折线逼近的旋转体，天然带缝合边。后续如果改成样条回转，要保留这个约束。
4. **网格参数与物理无关**：`max_mesh_size`/`min_mesh_size` 只影响 DAGMC 面网格，不影响 OpenMC 的 CSG 精度；CAD 折面化会引入几十 pcm 量级的系统偏差，重要基准仍应保留 CSG 模型。
5. **本机未执行转换**：Windows Python 3.12 没有 `openmc`、`gmsh`、`moab`、`cad_to_dagmc`；转换脚本应在装好 OpenMC 的 WSL/Linux 环境运行，STEP 是交接物。

## 6. CAD → OpenFOAM

NuScale 没有主泵，一回路是**密度差驱动的自然循环**，所以 CFD 的关注点不是"画得多细"，而是"回路是否连通、热源/热阱是否放对"：

1. **流体域** = RPV 内腔 − 堆芯实体 − 吊篮 − 下降段壁面。CAD 中 RPV/吊篮/下降段是相邻但独立的薄壁，布尔相减后能保持下降段环形通道贯通。
2. **堆芯用多孔区**：`core` LOD 的 37 个组件块直接作为 `cellZone`，用各向异性阻力/多孔换热模型代替 1 万根棒的显式网格；需要局部细节时再切到单组件 `assembly` LOD。
3. **自然循环边界**：CNV 外壁作为最终热阱（水池），RPV 外壁与 CNV 内壁之间是约 90 cm 的环形空间（真空/保温），CAD 中保持为两个独立壳体，**不要合并成厚壁管**。
4. **上腔室/蒸汽空间**：ecp 模型是堆芯基准，不含蒸汽发生器与稳压器；`module` LOD 只补了 RPV/CNV 包络。做完整自然循环前需要补螺旋管换热器与上升段，这部分目前是缺口。
5. **网格流程**：每个部件导出一个命名 STL → `snappyHexMesh` 的 `geometry` 段 → `locationInMesh` 选在下降段 → `cellZones` 标记堆芯多孔区。

## 7. 双向耦合的数据契约

| 方向 | 数据 | 载体 |
|---|---|---|
| OpenMC → OpenFOAM | 功率密度 W/cm³ | `RegularMesh` tally → 按 cell 映射成 `volScalarField` |
| OpenFOAM → OpenMC | 温度 K、水密度 g/cm³ | 按轴向/径向分区更新材料 `temperature`、`density` |
| 共同输入 | 几何、活性段高度、组件排布 | `params/nuscale_core.json` |

约定：两侧都用 CAD 的 `z=0` 基准；OpenMC mesh 的 `lower_left/upper_right` 由参数表里的活性段边界直接算出，避免手工填数。收敛判据建议用 `k_eff` 与堆芯出口温度同时稳定，而不是只看其中一个。

## 8. 与第 1 步 pin cell 的口径

`params/nuscale_pin.json` 已切到 NuScale DCA 几何：栅距 0.496 in、芯块直径 0.3195 in、包壳 0.326/0.374 in、富集度 3.1 wt%（DCA 组件的最高值）。此前 4.95 wt%、典型 17×17 尺寸的硼扫描结果已归档到 `results/archive_4p95/`，不再作为当前参数表的输出。

需要 OpenMC 重跑后，`k_inf` 曲线才与 CAD/组件模型同口径。做第 2 步（17×17 组件）时直接复用 `params/nuscale_core.json` 的 pin 与富集度分布即可。

## 9. 复现

```bash
python scripts/build_cad.py                 # 四级 LOD，约 1 分钟
python scripts/build_cad.py --levels core   # 只重建堆芯
python -m http.server 8765 --directory results/cad   # 浏览器看三维视图
```

## 10. 已知缺口

- RPV 全高、CNV 壁厚取自公开包络，不是 DCA 逐项尺寸。
- 重反射层水孔、堆芯围筒开孔、上下管座流通面积未建模。
- 未包含蒸汽发生器、稳压器、控制棒驱动机构；`module` 只是包络。
- DAGMC/OpenFOAM 转换与网格未在本机执行（缺工具链），STEP/STL 已准备好。
- Zenodo 的 Aldeen 2025.4 基准（661 MB）尚未拉取，可用于核对材料分区与组件排布。

## 11. 耦合实现与首轮结果（裂变堆芯 → 自然循环）

### 11.1 链路

```
nsc_bench/core.py        37 组件 2D OpenMC（每组件独立水材料）
scripts/run_core.py      k_eff + 每组件功率 → power.json
scripts/build_foam_case.py  power.json → 2D 轴对称 OpenFOAM 案例
scripts/run_foam_wsl.sh      blockMesh/topoSet/setFields/求解，路径无空格化
scripts/foam_post.py         环带平均温度 → IAPWS 密度 → densities.json
scripts/couple.py            串起 1–5，迭代并写 results/coupling/summary.json
```

耦合量：OpenMC 每组件功率按组件中心半径归到 4 个径向环 → CFD 环带热源；CFD 环带平均温度 → 15.5 MPa 液态水密度 → OpenMC 每组件水材料。基准温度 560 K 时水密度 0.752 g/cm³，与 OpenMC 侧的 0.998 g/cm³ 冷态形成约 0.035 的 k_eff 反馈。

### 11.2 CFD 拓扑

5° wedge（1/72 全环），`buoyantBoussinesqPimpleFoam` 瞬态，自适应时间步（maxCo 20，maxΔT 0.5 s），层流 + 多孔介质：

| 区域 | 半径 / m | 轴向 / m | 模型 |
|---|---|---|---|
| 堆芯 | 0.05–0.94 | 0.2–2.4 | 多孔 `d=1e5, f=28.20`，4 个环带热源 |
| 上升段 | 0.05–0.94 | 2.4–8.0 | 开通道 |
| 吊篮 | 0.94–0.96 | 0–8 | 阻塞 `d=1e10` |
| 蒸汽发生器 | 0.96–1.2255 | 4–8 | 多孔 `d=1e5, f=4.404` + 线性换热器，下降流 |
| 下降段 | 0.96–1.2255 | 0–4 | 开通道 |
| 上下腔室 | — | −0.4–0.2 / 8–10.5 | 开通道 |

关键建模决定：

1. **SG 必须在下降侧环形通道**。把 SG 放在堆芯正上方的中心柱里，冷却后的流体密度大于下方热流体，重力塌陷会让整个回路倒流。首轮正是这样，堆芯轴向速度在 +1.1 与 −1.1 m/s 之间翻转。
2. **不能有旁通**。SG 占满吊篮到 RPV 内壁的整个环隙，堆芯填到吊篮内壁，否则冷流体绕过堆芯或 SG，热量带不走。
3. **功率必须按扇区缩放**。wedge 只代表 1/72 体积，环功率要乘 `5/360` 再除以 wedge 体积；早期把全堆功率直接除 wedge 体积，等效功率密度放大 72 倍，温度场跑到 ±10⁴ K。
4. **物性用 15.5 MPa 真实值**。`β=2.45e-3 1/K`（560 K）、密度用 IAPWS-IF97 表插值；早期 `β=3.5e-4` 把自然循环驱动力低估约 7 倍。

### 11.3 首轮结果

`results/coupling/summary.json`：

| 迭代 | k_eff | Δk | 环带密度 / g·cm⁻³（内→外） | 堆芯轴向速度 | 下降段速度 |
|---|---|---|---|---|---|
| 0（冷态） | 1.25135 ± 0.00512 | — | 0.761 / 0.757 / 0.753 / 0.746 | — | — |
| 1 | 1.22297 ± 0.00232 | 0.0284 | 0.753 / 0.749 / 0.752 / 0.751 | +0.81 m/s | −0.92 m/s |
| 2 | 1.22409 ± 0.00205 | 0.0011 | 0.749 / 0.746 / 0.751 / 0.749 | +0.80 m/s | −0.92 m/s |

温度场：540–578 K，下降段 547–550 K，环带平均 560–563 K；`Δk=0.0011` 已在 1σ 以内，环带密度变化 0.0038 g/cm³，按 `|Δk|<5e-3` 且 `|Δρ|<5e-3` 判为收敛。

### 11.4 本轮缺口

- 只有水密度反馈，没有燃料多普勒与包壳温度反馈；294 K 截面库也不能真正体现热态谱。
- 瞬态只跑到几十秒量级，属于准稳态；严格收敛需要更长物理时间或稳态求解器。
- 堆芯 `ΔT` 约 14 K，仍低于真实 NuScale 的 ~30 K；多孔压降按 4 m/s 强制循环参考点标定，自然循环实际流速低得多。

### 11.5 SG 线性换热器与 40 kPa 占位压降

首轮的 SG 是固定体积热阱，热量移除与入口温度无关；堆芯/吊篮的多孔 `d` 也是拍值。本轮把两者换成可标定的模型。

**SG 换热器。** 在 SG 区写入 `scalarSemiImplicitSource`：

```
q''' = Su + Sp·T,   Sp = -k,   Su = k·T_sec
k = ln[(T_in - T_sec)/(T_out - T_sec)] / τ
```

取二次侧 `T_sec = 505 K`、设计进口 `570 K`、设计出口 `543 K`、停留时间 `τ = 4 s`，得 `k = 0.13420 1/s`、`Su = 67.771 K/s`、`Sp = -0.13420 1/s`。`Sp` 隐式处理，使温度场天然被二次侧温度限住，不会像固定热阱那样过冷或过热。对应 `fvOptions` 中的 `sgHeatExchanger (67.771140 -0.134200)`。

**压降标定。** 多孔源用 `DarcyForchheimer`，只保留惯性项 `ΔP = (ρ/2)·f·L·u²`（`d = 1e5` 仅用于抑制回流）。CFD 堆芯占满吊篮内截面 `2.776 m²`，真实棒束流通面积仅 `0.91 m²`，同一质量流量下 CFD 的表观速度低 3.05 倍，因此先用面积比把设计流速 4 m/s 折算成表观速度 `1.311 m/s`，再反解：

| 区域 | 参考 ΔP | 参考速度 | 长度 | `d` | `f` |
|---|---|---|---|---|---|
| 堆芯（37 组件） | 40 kPa（占位） | 4 m/s 棒束 → 1.311 m/s 表观 | 2.2 m | 1e5 | 28.20 |
| SG 管束 | 20 kPa（占位） | 1.74 m/s | 4.0 m | 1e5 | 4.404 |

40 kPa 是常规 PWR 组件在 4 m/s 下的量级，作为占位值把流程跑通；真实 NuScale 组件压降应在拿到棒束摩擦系数或试验数据后替换 `params/nuscale_core.json` 的 `assembly_design_pressure_drop_pa`，重跑 `build_foam_case.py` 即可，无需改代码。

**验证结果**（`results/coupling/hx_validation.json`，t = 130 s）：

| 量 | 值 |
|---|---|
| 堆芯轴向速度 | +0.245 m/s |
| 下降段轴向速度 | −0.344 m/s |
| 温度范围 | 521.4–620.0 K |
| SG 进口 / 出口温度 | 572.2 / 524.2 K |
| SG 热负荷 | 2.210 MW |
| 堆芯功率（wedge 份额） | 2.222 MW |
| 能量不平衡 | 0.53% |

能量不平衡由 t=0 的 36.7% 降到 130 s 的 0.53%；40–130 s 之间在 0.2–4% 间低频振荡（周期约 20 s），对应自然循环回路的密度波振荡，不是数值发散。用 t=30 s 场环带密度重跑 OpenMC（`results/coupling/hx_hot/power.json`）得热态 `k_eff = 1.21946 ± 0.00223`，环功率份额 3.66 / 22.74 / 35.41 / 38.19%。

**图集。** `results/figures/index.html` 汇总 Blender 渲染的 CAD（四级 LOD，含剖切）与 CFD 温度/速度场、能量平衡曲线、13 帧温度动画：

```bash
blender -b -P scripts/render_cad_blender.py -- --root . --out results/figures
python scripts/make_figures.py          # 场图 + GIF + 三维剖切
python scripts/make_gallery.py          # 生成 index.html
```

### 11.6 复现（耦合）

```bash
python scripts/build_cad.py                         # CAD（可选）
python scripts/couple.py --iterations 3             # OpenMC ↔ OpenFOAM 三轮
python scripts/build_foam_case.py --power results/core/power.json --case results/foam/case
wsl.exe bash scripts/run_foam_wsl.sh results/foam/case            # 首轮
wsl.exe bash scripts/run_foam_wsl.sh results/foam/case restart    # 用上一轮场续算
python scripts/foam_post.py --power results/core/power.json       # 环带密度 + 能量校核
```

`build_foam_case.py` 支持 `--params`（换参数表）与 `--sg-mode {hx,duty}`（线性换热器 / 旧固定热阱）。OpenFOAM 不能读含空格的路径，`run_foam_wsl.sh` 会把案例复制到 `~/nsc_case` 再求解，并把日志与时间目录拷回。重启时先备份最新时刻字段再清空工作目录，否则会静默退回 `setFields` 初场。

