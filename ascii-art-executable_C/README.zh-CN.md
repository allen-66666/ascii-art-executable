# ASCII Art Executable — 布局与自动放大（C 角色交付，v1.3）

> 中文说明（English 见 `README.md`）。六人课程项目 · 25 天 agentic coding · 分工契约见《项目启动方案
> （C 后端版）》，工程化要求按任务书 **《代码图案排版工具项目计划与六人分工_v1.3.docx》（v1.3）** 执行。
> 本工程基于 **B（图案输入与字符画）** 与 **F（检测器 + 图案保形）** 的可运行基线，
> 承担 **C 的布局与自动放大任务（v1.3 角色名，对应 `fit_layout`）**，并修复 B 的 `shape_ok` 类型标注 bug。
>
> 说明：代码中的 `CBackend`、`backends/` 等是实现该角色的具体模块名，角色任务名以 v1.3 为准。
>
> 一句话：**给一段代码 + 一张图片 → 生成"功能相同、形状像图片、能编译、能运行"的 C 源文件。**
> 图片不限猫，给什么图就成什么形状。

---

## 一、这个包里的内容

```
ascii-art-executable_C/
├─ run.py                  ← 【C】双击交互式启动器
├─ README.md               ← English README
├─ README.zh-CN.md         ← 本文件（中文说明）
├─ FILE_GUIDE.md           ← 逐个文件解释作用
├─ C_对接说明.md           ← 给 D/E 的对接契约
├─ requirements.txt        ← 依赖：Pillow、pytest
├─ shared/                 ← 五共享类型（B/F/C 共同）
├─ ascii_art_executable/
│   ├─ grid.py             ← 【B】build_grid -> PixelGrid
│   ├─ shapecheck.py       ← 【F】check_shape / detect / render_report
│   └─ backends/
│       ├─ base.py         ← 【C】Backend 抽象基类
│       ├─ c_widthsafe.py  ← 【C】等宽清洗 + 安全字符集
│       ├─ c_seam.py       ← 【C】保列接缝（语句嵌入图案）
│       ├─ c_doc.py        ← 【C】解释代码作用的英文注释
│       ├─ c_parser.py     ← 【C】把真实 C 源码解析成骨架
│       ├─ c_fill.py       ← 【C】块注释填充 + 源码组装（v0/v1a/v1b）
│       ├─ c_backend.py    ← 【C】CBackend：fill / verify / 编译器探测
│       ├─ c_tokenfill.py  ← 【C】v2 + v1.3：距离场明暗、特征与轮廓工具
│       └─ shaper.py       ← 【C】高层入口：代码 + 图片 -> 保形代码
├─ scripts/
│   ├─ build_shaped.py     ← 【C】任意图片 + 代码 -> 保形代码（命令行）
│   ├─ demo_c.py           ← 【C】猫演示
│   ├─ demo_grid.py        ← 【B】演示
│   └─ demo_bf.py          ← 【F】演示
└─ tests/                  ← 共 59 个测试（B + F + C）
```

---

## 二、环境准备（首次）

```powershell
cd <本工程目录>
python -m pip install -r requirements.txt
```

> B 原工程自带 `.venv` 是 macOS 格式，Windows 不可用，直接用系统 Python 即可。

---

## 三、最简单的方式：双击 `run.py`

`run.py` 是面向不想记命令的用户的交互式启动器。双击它（`.py` 已关联 Python），按提示依次回答：

1. 图片路径
2. C 代码路径
3. 输出文件
4. 模式（推荐 `v2`）
5. 宽度（填 `auto` 或数字）

随后它会生成、做保形检查和编译运行验证，并打印输出路径。路径用 `/` 或 `\` 都行，首尾引号可带可不带。
**所有输入必填**：直接回车不会取默认值，而会提示 "No input received. Please enter a value." 并重新询问。

若双击没反应，右键 `run.py` → 打开方式 → 选择 Python，或运行 `python run.py`。

---

## 四、命令行用法

```powershell
# 参数：<图片> [代码.c] [输出.c] [模式] [宽度]
python scripts/build_shaped.py demo/donut.png demo/donut_input.c demo/donut_v2.c v2 60
python scripts/build_shaped.py demo/cat.png demo/table_input.c demo/table_output.c v2
python scripts/build_shaped.py demo/heart.png demo/verify_input.c demo/heart_v2.c v2 60
```

不指定宽度时，`build_shaped.py` 用 `recommend_width_for`（同时打印内部特征报告）；显式宽度导致
特征过小时会打 WARNING。

### 直接编译运行生成的 .c

```powershell
& "C:\Program Files (x86)\Dev-Cpp\MinGW64\bin\gcc.exe" demo/donut_v2.c -o donut
.\donut.exe
```

---

## 五、任务书 v1.3 给 C 的任务（落地情况）

### 5.1 工程化要求（已落地）

1. **依赖注入**：`shape_code(..., grid_builder=None, backend=None)` 默认用真实 B 网格构造器和
   C 后端，也可注入假构造器/假后端隔离调试；`recommend_feature_width(..., grid_builder=None)`
   同样支持。
2. **量化尺寸估算**：`recommend_width(code_text, *, run_fraction=0.28, min_w=40,
   max_w=LAYOUT_MAX_WIDTH)` 按"最长 token ÷ 侧 run 占比"计算再 clamp 到 [40, 200]（donut → 65）。
3. **正式布局上限与统一失败（v1.4）**：`LAYOUT_MAX_WIDTH = 200`、`LAYOUT_MAX_ATTEMPTS = 12`、
   `LAYOUT_GROWTH = 1.25`、结构化异常 `LayoutLimitError(RuntimeError)`。单次尝试失败会放大宽度
   重试并记录每次尝试；成功时记录在 `sk.attempt_history`，重试用尽时异常的 `code` 与
   `details["attempt_history"]` 带出同一批记录，不再静默产出坏文件或裸 `IndexError`。
4. **最小词法分隔**：`_needs_space(prev, tok)` 仅在两个 token 相连会改变词法时才插空格，其余靠
   C 的空白不敏感性处理。

### 5.2 v2 明暗：距离场驱动（形状无关）

当前明暗**不使用方向光**，改用距离场，保证任意形状通用：

- `distance_field(grid)`：chamfer 两遍扫描，算每个前景格到最近背景格的距离（背景=0 距离源、
  前景=inf 待松弛，斜向步长 √2）。
- `shade_char(x, y)`：`t = min(1, dist/_D0)`，`b = _FLOOR + (1-_FLOOR)*t`，再映射 16 级字符集。
  参数 **`_FLOOR = 0.55`、`_D0 = 6.0`**。
- 效果：边缘（距离小）字符稀疏、向内平滑变密、主体饱满；无方向阴影、无单调整行同一字符。

### 5.3 关键内部特征保留（猫眼不丢失）

- `internal_holes(grid)`：背景连通分量中不触碰网格边框的即内部孔洞（泛洪，纯几何）。
- `recommend_feature_width(..., min_hole_cells=10, ref_w=160, ref_min=12)`：高参考分辨率下过滤
  噪声，二分搜索最小宽度使每个有意义孔洞达标。
- `recommend_width_for(code_text, image_path)`：取 token 宽度与特征宽度的**较大值**。
- `feature_report(..., min_hole_cells=10, noise_floor=4)`：列孔洞尺寸并标注 undersized/ok。
- 猫自动选宽 81，两眼各 64 格，特征报告 ok。

### 5.4 外轮廓修复

`repair_outer_silhouette(grid, *, max_notch=6)`：构造逐行边缘包络（边缘每行最多向内移
`max_notch`，正/反两遍松弛），只把外边缘带内的背景格提升为前景，不碰内部孔洞和小胡须缝隙。
`shape_code` 在填充前先修复（`isinstance` 守卫），`render_v2` 内保留一次幂等调用。猫胡须区左边缘
从列 30 收回到 17–23，内部孔洞不变。

### 5.5 未采纳的 v1.3 项（不适用/过度设计）

- 把填充步骤拆给 D、本角色只做布局：实际实现把布局与填充合并在同一套代码中完成，未拆分角色。
- 强制 libclang 词法：正则分词够用，避免重依赖。
- 硬 800×600 / 5 秒 / 单调时钟 RunContext 取消、带耗时的 AttemptRecord：对小型确定性离线工具
  属过度设计。

---

## 六、档位（启动方案 v0 / v1 / v2 的实现映射）

| 档位 | 形状承载方式 | 实测指标 |
|---|---|---|
| **v2** | 真实代码 token + 英文注释沿轮廓排布，其余格由距离场用 16 级字符明暗（边缘疏、内部密） | 猫 99.1% / 甜甜圈 97.6% / 心形 98.2%，precision 100%，均编译运行通过 |
| v1b | 真实语句 `*/ 语句 /*` 嵌进空白缝 | recall 100%，多余格是必需的真实代码 |
| v1a | 图案在块注释、语句在其后 | recall=precision=100%、extra=0（安全线） |
| v0 | 图案由可执行 `printf` 逐行打印 | 形状来自真实执行的代码，天然保形 |

> `mode="auto"` 先试 v1b 再降级 v1a；要 token 描边效果请显式传 `v2`。

---

## 七、关于 gcc

`CBackend` 先探 PATH 上的 `gcc`/`clang`，再回退已知 Dev-C++ 路径。
- **找到** → 编译 → 运行 → 比对 stdout → 保形。
- **找不到** → 只做保形与结构校验，注明"跳过编译"（降级，不是失败）。

Dev-C++ 5.11 自带 MinGW64 gcc 4.9.2，位于 `C:\Program Files (x86)\Dev-Cpp\MinGW64\bin\gcc.exe`，
路径已内置并实测，无需额外下载。编译用完整 `ci.path`（不依赖 PATH），subprocess 以
`errors="replace"` 读取以兼容 GBK 终端。

> 说明：输出是纯文本、没有真实光。明暗只是一个决定用哪个字符的确定性函数，立体感完全由字符
> 密度和字符选择承载，不调整任何真实亮度。

---

## 八、本机验证结果（2026-11-04）

- `python -m pytest tests -q` → **59 passed, 5 subtests passed**。
- 猫（自动宽 81）：1468/1482（99.1%）、precision 100%、轮廓闭合、眼孔清晰，gcc 编译运行乘法表正确。
- 甜甜圈（宽 60）：680/697（97.6%）、precision 100%，gcc 输出 total=91。
- 心形（宽 60）：656/668（98.2%），gcc 输出 sum=15。
- 剩余缺失格是被背景包围的孤立单格 run（长度 1，放不下 `/*` 标记），不在外轮廓上，不影响闭合。
