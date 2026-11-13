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
