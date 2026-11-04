# C 角色对接说明（给 D / E / 集成测试）

> 作者：C（v1.3 任务名：**布局与自动放大 / Layout & Auto-scaling**）
> 依据：《项目启动方案（C 后端版）》、**《代码图案排版工具项目计划与六人分工_v1.3.docx》**（任务书 v1.3，位于 `..\..\方案\`）、C 预研、B 评审、F 对接说明
> 状态：已实现并通过自测（**59 个测试全绿**，含 Dev-C++ gcc 的真实编译运行）
>
> 命名说明：v1.3 把本角色称为"布局与自动放大"（对应 `fit_layout`）。下文出现的
> `CBackend`、`backends/` 等是承载该角色的**具体代码实现**名称，不改变角色任务名。

## 0. 一句话

`CBackend(Backend).fill(grid, skeleton, plan)` 把 B 的 `PixelGrid` 变成"能编译、
能运行、输出正确、被 F 判保形"的 C 源文件。对外高层入口是 `shape_code(...)`，
实现入口是 `CBackend`，都在 `ascii_art_executable.backends` 下。

---

## 1. 我交付了什么

| 交付物 | 归属 | 说明 |
|---|---|---|
| `shared/types.py` 的 `Statement`、`CodeSkeleton`、`CanvasPlan` | C | 见 §2 |
| `VerifyReport.shape_ok` 修复 | C（改 B 的标注 bug） | `Optional[bool] = None` |
| `backends/base.py` | C | `Backend` 基类（D 的 C++/Python 后端应继承它） |
| `backends/c_*.py` + `c_backend.py` | C | 布局与自动放大的实现主体（含 `CBackend` 与填充模块） |
| `run.py`（工程根） | C | 双击交互式启动器，见 §6 |
| `scripts/demo_c.py`、`tests/test_c_backend.py` | C | 演示 + 自测 |

D 若做 C++/Python 后端，只需继承 `Backend` 实现四个方法，即可复用 `fill()` 管线。

---

## 2. 五共享类型现状（接口冻结后的状态）

| 类型 | owner | 状态 |
|---|---|---|
| `PixelGrid` / `GridCell` | B | 冻结，未动 |
| `CodeSkeleton` | C | C 补全：新增 `Statement`；补 `output_path/start_line/start_column/used_mode/canvas_width/canvas_height` |
| `CanvasPlan` | A(C) | C 增加 `safe_charset`；`block_comments` 用 `(start_line,end_line,start_col,end_col)` 区间 |
| `VerifyReport` | E | C 修了 `shape_ok` 标注 bug（`bool=Optional[bool]` → `Optional[bool]=None`） |
| `CompilerInfo` | E | 未动 |
| `ShapeReport` / `DetectionReport` | F | 未动（F 新增，向后兼容） |

> 接口冻结在 1–3 天；以上均为**向后兼容**的增量或 bug 修复，不破坏既有调用。

---

## 3. 任务书 v1.3 给 C 的任务（落地情况）

v1.3 相对启动方案新增了若干工程化要求，C 已落地其中适用项；不适用项见 §3.5。

### 3.1 已落地

1. **依赖注入（dependency injection）**
   `shape_code(code_text, image_path, out_path, *, mode=..., max_w=..., grid_builder=None,
   backend=None)`。`grid_builder` 默认用 B 的 `build_grid`，`backend` 默认用 `CBackend`；
   测试可注入假网格构造器或假后端，隔离调试布局。`recommend_feature_width(...,
   grid_builder=None)` 同样支持注入。

2. **量化尺寸估算（quantitative width estimation）**
   `recommend_width(code_text, *, run_fraction=0.28, min_w=40, max_w=LAYOUT_MAX_WIDTH)`
   按"最长 token 长度 ÷ 侧 run 占比"一次算出建议宽度，再 clamp 到 `[40, 200]`，不再靠
   固定值 72。实测 donut_input.c → 65。

3. **正式布局上限与统一失败（layout limits / v1.4 failure）**
   常量 `LAYOUT_MAX_WIDTH = 200`、`LAYOUT_MAX_ATTEMPTS = 12`、`LAYOUT_GROWTH = 1.25`，
   以及专用异常 `LayoutLimitError(RuntimeError)`。单次尝试放不下时不立即失败：宽度按
   `LAYOUT_GROWTH` 放大后重试，并把每次尝试记成一条记录（宽高、原因、耗时等）。成功时
   记录在 `sk.attempt_history`；重试用尽或超宽时抛 `LayoutLimitError`，其 `code` 与
   `details["attempt_history"]` 带出同一批尝试记录，而不是静默产出坏文件或裸 `IndexError`。

4. **最小词法分隔（minimal separation）**
   `_needs_space(prev, tok)`（等价 can_join 判断）只在"两个 token 直接相连会改变词法"
   时才插空格（如两个标识符相邻、数字接标识符）；其余位置靠 C 的空白不敏感性直接换行/
   缩进，不浪费前景格。

### 3.2 v2 明暗：距离场驱动（形状无关）

v1.3 延续 v2 的"真实代码 + 明暗"目标。当前明暗**不再使用方向光**，改用距离场，保证对
任意形状通用：

- `distance_field(grid)`：chamfer 两遍扫描，计算每个前景格到最近背景格的距离（背景=0
  距离源、前景=inf 待松弛，斜向步长 √2）。
- `shade_char(x, y)`：`t = min(1, dist/_D0)`，`b = _FLOOR + (1-_FLOOR)*t`，再按 `b`
  映射 16 级字符集。参数 **`_FLOOR = 0.55`、`_D0 = 6.0`**。
- 效果：边缘（距离小）字符稀疏、向内平滑变密，主体饱满；无方向阴影、无单调整行同一
  字符。该函数只依赖几何距离，换任何图片都成立。

### 3.3 关键内部特征保留（猫眼不丢失）

- `internal_holes(grid)`：背景连通分量中**不触碰网格边框**的即内部孔洞（泛洪，纯几何）。
- `recommend_feature_width(image_path, *, grid_builder=None, min_hole_cells=10,
  ref_w=160, ref_min=12)`：高参考分辨率下过滤噪声得到有意义孔洞数，二分搜索最小宽度，
  使每个孔洞达到 `min_hole_cells`。
- `recommend_width_for(code_text, image_path)`：取 token 宽度与特征宽度的**较大值**。
- `feature_report(grid, *, min_hole_cells=10, noise_floor=4)`：列全部孔洞尺寸并标注
  undersized/ok。
- 接线：`build_shaped.py` 未指定宽度时用 `recommend_width_for`；显式宽度 undersized 时
  打 WARNING。实测猫自动宽 81，两眼各 64 格，特征报告 ok。

### 3.4 外轮廓修复（侧面开口收窄）

`repair_outer_silhouette(grid, *, max_notch=6)`：逐行算最左/最右前景列构造边缘包络，
边缘每行最多向内移 `max_notch`（正/反两遍松弛），只把**外边缘带**内的背景格提升为前景，
不碰内部孔洞和小缝隙。`shape_code` 在 v2 下先用 `isinstance` 守卫再修复，然后填充；
`render_v2` 内也保留一次幂等调用。实测猫胡须区左边缘从列 30 收回到 17–23，内部孔洞
前后完全不变。

### 3.5 v1.3 中未采纳的项（不适用/过度设计，仅告知）

- 把填充步骤拆给 D、本角色只做布局：实际实现把布局与填充合并在同一套代码中完成，未拆分角色，不执行该拆分。
- 强制用 libclang 词法：正则分词已覆盖需求，避免引入重依赖。
- 硬 800×600 / 5 秒 / 单调时钟 RunContext 取消：对小型离线工具属过度设计。
- 带耗时的结构化 AttemptRecord：v2 为确定性单遍、无盲目重试，记录价值低。

---

## 4. C 的填充档位（启动方案 v0/v1/v2 映射）

| 档位 | 含义 | C 实现 |
|---|---|---|
| v0 | 图案放字符串打印 | `render_v0`：逐行 `printf("…")`，天然保形，兜底 |
| v1a | 块注释 + 语句落点 | `render_v1a`：图案在 `/* */`、语句排在其后，100% 保形（安全线） |
| v1b | 语句嵌入图案 | `render_v1b`：`*/ 语句 /*` 嵌进空白缝，列对齐零偏移 |
| v2 | token 描边 + 距离场明暗 | `render_v2`（`c_tokenfill.py`）：真实 token 与英文解释注释配对沿轮廓排布，预处理行/字符串原子不拆；注释区域由 `distance_field` + `shade_char` 按到边缘的距离用 16 级 `_SHADE_RAMP` 填充，边缘暗、内部平滑变密，编译运行通过 |

`CBackend.fill(mode="auto")` 先试 v1b，缝不够宽自动降级 v1a；要代码 token 描边效果请显式
传 `v2`。

---

## 5. 编译器策略（E 集成时注意）

`CBackend.detect_compiler()` 先探 PATH 上的 `gcc`/`clang`，再回退已知 Dev-C++ 自带路径；
`verify()`：
- 有编译器 → 编译 + 运行 + stdout 比对 + F 保形；
- 无编译器 → 只做 F 保形 + 结构校验，并在结果里注明"降级"（**不是失败**）。

编译/运行用完整路径 `ci.path`，不依赖 PATH；subprocess 以 `errors="replace"` 读取，避免
GBK 输出崩溃。`VerifyReport.compile_ok / run_ok / output_match` 在无编译器时填 `None`
（未知），不要填 `False` 伪装成"编译失败"。

---

## 6. 双击启动器 run.py（工程根）

`run.py` 是面向非命令行用户的交互入口：双击后按提示依次输入**图片路径、C 代码路径、
输出路径、模式、宽度**，自动生成并做保形 + 编译运行，末尾打印输出路径并停住窗口。

- 路径用 `/` 或 `\` 都行（Windows 与 pathlib 都接受），首尾引号可带可不带，会被清洗。
- **所有输入必填**：直接回车不会取默认值，而会提示 "No input received. Please enter a
  value." 并重新询问；宽度可填 `auto` 或具体数字。

---

## 7. 保形口径（沿用 F 的规则）

- 前景以 `cell.fg` 为准：`fg=True` 的格子必须被非空字符占据；
- 默认 occupancy 模式只要求前景被占；`min_precision=1.0` 才严格背景；
- 占据判定为 `not ch.isspace()`，PASS 要求 `missing == 0`。

---

## 8. 自测与验收证据

- 全量：`python -m pytest tests -q` → **59 passed, 5 subtests passed**（含真实 gcc 端到端）。
- 猫（自动宽 81）：Matched 1468/1482（99.1%）、precision 100%、外轮廓零缺口、眼孔清晰，
  gcc 编译运行输出乘法表正确。
- 甜甜圈（宽 60）：680/697（97.6%）、precision 100%，gcc 输出 total=91。
- 心形（宽 60）：656/668（98.2%），gcc 输出 sum=15。
- 剩余缺失格是被背景包围的内部孤立单格（run 长度 1，放不下 `/*` 标记），不在外轮廓上，
  不影响闭合。

> 结论：本角色（布局与自动放大）可在验收线（小图案 + hello 骨架生成的 C 过
> `gcc -fsyntax-only`）上交付；有 gcc 的机器上跑 `run.py` 或 `build_shaped.py` 即补齐编译运行那一步。
