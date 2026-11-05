# FILE_GUIDE — 工程内每个文件的作用（C 角色交付）

> C 在 v1.3 中的角色名是"布局与自动放大 / Layout & Auto-scaling"（对应 `fit_layout`）；
> `CBackend`、`backends/` 等是承载该角色的具体代码模块名。
> 路径基准：`ascii-art-executable_C/`。标注【B】=B 写的、【F】=F 写的、【C】=C 写的、
> 【生成】=运行脚本后产生的产物（可删，重跑会再生成）。

## 根目录

| 文件 | 作者 | 作用 |
|---|---|---|
| `run.py` | C | **双击交互式启动器**：按提示输入图片/代码/输出/模式/宽度，生成并验证；所有输入必填 |
| `run_selfcheck.bat` | C | **双击一键检验**：无需找代码/图片，自动用内置素材跑 6 个案例并显示示例结果（调 `scripts/selfcheck.py`） |
| `README.md` | C | 英文总入口：环境准备、如何运行、C 在 B/F 基础上做了什么 |
| `README.zh-CN.md` | C | 中文总入口 |
| `C_对接说明.md` | C | 给 D/E 的对接契约：v1.3 任务、共享类型、坐标语义、档位、编译器策略 |
| `FILE_GUIDE.md` | C | 本文件：逐个解释每个文件干什么 |
| `requirements.txt` | B | 依赖清单：Pillow、pytest，`python -m pip install -r` 用 |

## shared/ — 五共享类型（跨模块唯一数据源）

| 文件 | 作用 |
|---|---|
| `types.py` | 所有跨模块数据结构：`PixelGrid`(B)、`CodeSkeleton`+`Statement`(C，含 `start_line/start_column/canvas_width/canvas_height` 图案区域几何)、`CanvasPlan`(A+C)、`VerifyReport`(E，C 修了 `shape_ok` bug)、`CompilerInfo`(E)、`ShapeReport`/`DetectionReport`(F) |
| `__init__.py` | 统一导出上述类型，`from shared import ...` 用 |

## codeart/ — B 的 v2 形状掩码模块（依赖注入来源）

| 文件 | 作用 |
|---|---|
| `shapes.py` | `build_mask(ShapeSpec, SizeRequest, FontMetrics) -> Mask`：生成 circle/cat/code 三种布尔掩码；`Mask.allowed[row][col]` 为 True 表示可填；含 `ShapeSpec`/`SizeRequest`/`FontMetrics`/`ShapeError`/`geometry_metrics` |
| `__init__.py` | 导出 `build_mask`、`Mask`、`ShapeSpec`、`SizeRequest`、`FontMetrics` 等 |

`SizeRequest(32)` 实测尺寸：circle 64×32、cat 64×32、code 178×32（32 = 高度行数）。

## ascii_art_executable/ — 主代码包

| 文件 | 作者 | 作用 |
|---|---|---|
| `grid.py` | B | `build_grid(src, charset, max_w) -> PixelGrid`：图片/口号降采样成字符网格 |
| `shapecheck.py` | F | `check_shape`/`detect`/`render_report`：保形校验 + 语言检测（C 的验收裁判） |
| `__init__.py` | C | 包导出（B 的入口） |

### ascii_art_executable/backends/ — 布局与自动放大的实现模块（本角色核心）

| 文件 | 作用 |
|---|---|
| `base.py` | `Backend` 抽象基类：四方法 + 公共 `fill()`；D 的后端继承它 |
| `c_widthsafe.py` | 等宽清洗：`*/→*|`、`??→?~`、`\\→/`、`#→+`（行长零变化），定义 `C_SAFE_CHARSET` |
| `c_seam.py` | 保列接缝：两阶段选行（行号升序防顺序反转）+ `build_seam_row`（语句嵌入、右段零偏移） |
| `c_doc.py` | 为每条真实语句生成"解释这行作用"的英文注释：`explain`（完整句）、`short_explain`（v2 用的简短短语）、图案块英文标注 |
| `c_parser.py` | 把真实 C 源码解析成 `CodeSkeleton`；`extract_main_parts` 提取 main 内真实语句；`validate_c_source` + `SourceInputError` 拒绝非 C/非 ASCII/缺 main 的输入（如 Python） |
| `c_fill.py` | 块注释填充 + 源码组装，三档位 v0/v1a/v1b，真实语句带英文注释 |
| `c_backend.py` | `CBackend`：`fill(grid,skeleton,plan)` 主入口、`verify`（编译+运行+保形）、`detect_compiler`（含 Dev-C++ 路径回退）、`make_hello_skeleton` |
| `c_tokenfill.py` | **v2 与 v1.3 工程化主体**，见下表 |
| `mask_adapter.py` | 把 B 的 `codeart.build_mask` 布尔掩码适配成 `PixelGrid`：`mask_to_pixelgrid`、`make_mask_builder`（重试时按比例放大掩码）、`shape_code_for_shape` 一站式入口；不改冻结类型 |
| `shaper.py` | 高层入口 `shape_code(code, image, out, *, mode, max_w, grid_builder=None, backend=None)`：代码+图片（或形状名）→功能相同且保形的 C 文件；v2 下先 `repair_outer_silhouette` 再填充 |
| `__init__.py` | 导出 `Backend/CBackend/make_hello_skeleton/shape_code` |

### c_tokenfill.py 内的关键部件

| 部件 | 作用 |
|---|---|
| `tokenize_c` / `_needs_space` | 正则分词；仅在词法会改变时才插空格（v1.3 最小分隔） |
| `recommend_width` | 量化宽度：最长 token ÷ `_RUN_FRACTION=0.28`，clamp [40, 200] |
| `LAYOUT_MAX_WIDTH=200` / `LAYOUT_MAX_ATTEMPTS=12` / `LAYOUT_GROWTH=1.25` / `LayoutLimitError` | v1.4 布局上限、有界重试与结构化异常（含 `code`/`details` 里的尝试历史） |
| `distance_field` | chamfer 两遍算每个前景格到最近背景格的距离（背景=0、前景=inf） |
| `shade_char`（`_FLOOR=0.55`、`_D0=6.0`） | 距离归一化映射 16 级 `_SHADE_RAMP`，边缘暗、内部平滑变密 |
| `internal_holes` / `recommend_feature_width` / `recommend_width_for` / `feature_report` | 内部孔洞几何分析与自动宽度，保证猫眼等关键特征不丢失 |
| `repair_outer_silhouette(max_notch=6)` | 外轮廓边缘包络修复，收窄侧面开口，不碰内部孔洞 |
| `render_v2` | 分词→item 流→距离场明暗→特征避让→逐行跨孔填充，产出可编译运行的 token 描边代码 |

## scripts/ — 可直接运行的演示/工具

| 文件 | 作者 | 作用 |
|---|---|---|
| `build_shaped.py` | C | 命令行：任意图片（或形状名 circle/cat/CODE）+ 任意 C 代码 → 保形代码；形状名模式第 5 个参数为高度行数，图片模式未指定宽度用 `recommend_width_for`，显式 undersized 给 WARNING |
| `selfcheck.py` | C | **零输入一键检验**：用内置 demo 素材和形状名跑 6 个案例，编译运行并与原程序比对，打印汇总表和猫形示例，退出码反映是否全过 |
| `demo_c.py` | C | C 演示：画猫 → fill → F 保形 → gcc 编译运行 |
| `demo_grid.py` | B | B 演示：打印字符网格 |
| `demo_bf.py` | F | F 演示：保形 + 检测报告 |

## tests/ — 测试（共 100 个）

| 文件 | 作者 | 作用 |
|---|---|---|
| `test_c_backend.py` | C | C 的测试：清洗/接缝/填充/保形/明暗 ramp/recommend_width/依赖注入/distance_field/internal_holes/特征宽度/轮廓闭合/轮廓修复/输入校验/端到端（无 gcc 自动跳过） |
| `test_mask_injection.py` | C | mask 接入测试：假 `build_mask` 注入、三种尺寸、重试放大、图片路径不变、真实 gcc 端到端 |
| `test_shapes.py` | B | B 的 `codeart` 形状掩码测试（用 `fixtures/shapes/` 基准 JSON） |
| `test_grid.py` | B | B 的网格测试 |
| `test_shapecheck.py` | F | F 的保形与检测测试（含 subtests） |

## docs/ — 模块文档

| 文件 | 作用 |
|---|---|
| `modules/shapes.md` / `shapes.zh-CN.md` | B 的 `codeart.shapes` 英文/中文说明 |

## demo/ — 素材与示例

| 文件 | 状态 | 作用 |
|---|---|---|
| `cat.png` | 素材 | 猫的源图片（560×560，黑眼带白竖瞳、三对水平胡须） |
| `heart.png` | 素材 | 实心心形（证明任意形状） |
| `donut.png` | 素材 | 椭圆环（甜甜圈）剪影，v2 目标形状 |
| `table_input.c` | 示例 | 可输入的任意代码（乘法表） |
| `verify_input.c` | 示例 | 另一个可输入示例（循环求和） |
| `donut_input.c` | 示例 | v2 演示用的功能代码（循环+平方） |
| `table_output.c` | 生成 | 乘法表被做成猫形、带英文注释的 v2 结果（眼睛清晰、轮廓闭合） |
| `donut_v2.c` | 生成 | 真实 token 排布成圆环、距离场明暗的 v2 结果 |
| `heart_v2.c` | 生成 | 同一功能排布成心形（v2） |
| `c/skeleton.c` | 生成 | demo_c 产出的猫形 C 源文件 |
| `shaped/heart_v1a.c` | 生成 | 心形 v1a 结果（100% 精度） |
| `shaped/cat60.c` | 生成 | 显式宽度 60 的 undersized 警告示例 |

> 说明：所有 `.exe` 是编译产物，已从交付中移除（可随时用 gcc 重新生成）；
> `__pycache__/`、`.pytest_cache/` 是自动缓存，可随时删除，不影响功能。
