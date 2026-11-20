# EdgeWeaver

EdgeWeaver 是一个 Linux 原生的时序图编辑器，读写 legacy `.tim` 时序文件。

---

## 已实现功能

- **`.tim` 读写**：版本 011 / 010；未修改的文件加载后再保存可做到**字节级完全一致**。
- **时序元素**：时钟（Clock）、信号（Signal）、总线（Bus）、分隔符（Separator）。
- **编辑**：高/低/高阻绘制、总线绘制、擦除、选择与删除单元格；添加/重命名/删除行；
  文档参数（槽宽、可见槽数、信号高度、名称列宽）。
- **三态信号**：0 / 1 / Z；Z 画在高低电平正中间，工具栏 `Z` 工具或快捷键 `Z` 绘制。
  总线行的高阻段同样画成中间高度的一条横线（不画总线上下轨、阴影和值文本）。
- **边沿样式**：每行可切换垂直边沿（ideal）或斜边（non-ideal），并可设置斜边宽度；
  时钟和非总线信号都支持。
- **时钟周期数**：工具栏 `Cycles:` 可直接增减可见时钟周期数，修改后自动重生成所有时钟；
  `Signal/Clock Properties` 还可设置时钟周期、占空比、起始电平。
- **标注**：文本标签、信号间关系箭头、时间断裂（Time Break）；
  `Edit → Annotations...` 可集中查看和删除。
- **边沿间隔测量**：选择两个边沿，画两条竖线和一条双向水平箭头，箭头上方可填写
  中文/英文/数字/单位（`us`、`ms`、`ns` 等）。用 Select 工具上下拖动刻度线可
  调整高度（竖线随之伸缩），选中后方向键 1 px / Shift+方向键 10 px 微调；
  右键可修改颜色（默认黑色）、文字，`Del` 删除；也可在
  `Edit → Annotations → Measurements` 中集中管理。
- **箭头编辑**：选择工具下点击箭头即可选中；拖两端改信号/槽位，拖弯曲手柄改弧度，
  拖箭头其它位置整体移动；`Del` 删除；双击或 `Edit → Edit Arrow...` 精确编辑。
- **箭头样式**：工具栏 `Arrow:` 下拉选择 Straight / Angled / Bezier / Floating，
  已有箭头可在 Edit Arrow 对话框中切换；样式数值写回 `.tim` 的 type 字段。
- **边沿吸附**：创建/拖动箭头端点时自动吸附到目标信号的跳变边沿
  （上升/下降/总线跳变）；附近没有边沿时退回最近网格边界；拖动时显示蓝色虚线引导。
- **导出**：EMF 矢量图、PNG、SVG（可导出透明背景）、PDF、CSV、Timing XML。
- **导入**：Timing XML、CSV。
- **CLI**：无窗口命令 `draw` / `convert`，用 JSON 描述生成时序图，便于脚本和 AI 调用（见 `docs/cli.md`）。
- **显示**：网格/时钟周期线、信号名、名称/波形分栏线、总线值、包围矩形开关；缩放/适应窗口。
- **其他**：拖放打开 `.tim`、最近目录记忆、GBK/GB18030 中文标签显示（默认）。
- **无网络、无数据库、无外部运行时依赖**（除 PyQt6）。

## 运行

```bash
cd /home/studig/Documents/project/EdgeWeaver
./run.sh
# 或直接打开文件：
./run.sh "/path/to/2-3-2.tim"
```

命令行（无窗口，供脚本/AI 使用）：

```bash
./run-cli.sh draw spec.json --out timing.tim --out timing.svg --transparent
./run-cli.sh convert timing.tim --out timing.emf --out timing.png
./run-cli.sh describe          # 打印完整 CLI/JSON 说明
```

完整说明见 [`docs/cli.md`](docs/cli.md)。

依赖：Linux、Python 3.10+、PyQt6（已在 Python 3.14 + PyQt6 6.10.2 下验证）。

```bash
/usr/bin/python3 -m pip install --user -r requirements.txt
```

## 快捷键

| 按键 | 功能 |
|---|---|
| `Ctrl+N/O/S/Shift+S` | 新建 / 打开 / 保存 / 另存为 |
| `Ctrl+Z` / `Ctrl+Y` | 撤销 / 重做 |
| `V` | 选择工具 |
| `H` / `L` | 画高 / 低 |
| `Z` | 画高阻 Z（高低之间） |
| `B` | 画总线（值 4） |
| `T` | 放置文本标签 |
| `A` | 画关系箭头（先点源，再点目标） |
| `M` | 边沿间隔测量（先点起点边沿，再点终点边沿，输入文字） |
| `K` | 时间断裂 |
| `E` | 擦除 |
| `F2` | Signal/Clock Properties（边沿、时钟参数） |
| `Del` | 清除选中单元格；箭头选中时删除箭头 |
| `Ctrl++` / `Ctrl+-` / `Ctrl+0` | 放大 / 缩小 / 适应窗口 |
| `Esc` | 取消当前箭头起点/选择 |
| 选中箭头后拖端点 | 修改源/目标信号与槽位 |
| 选中箭头后拖蓝色弯曲手柄 | 调整弧度（offset） |
| 选中箭头后拖其它位置 | 整体移动箭头 |
| 箭头端点靠近信号跳变 | 自动吸附到该边沿（上升/下降/总线跳变） |
| 选中箭头后方向键 | 按 1 px 微调箭头整体位置 |
| 选中箭头后 Shift+方向键 | 按 10 px 微调箭头整体位置 |
| 选中测量后上下方向键 | 调整刻度线高度 1 px（竖线随之伸缩） |
| 选中测量后左右方向键 | 测量整体左右移动 1 px |
| 选中测量后 Shift+方向键 | 上述调整按 10 px 步进 |

## 项目结构

```
EdgeWeaver/
├── run.sh
├── run-cli.sh               # 无窗口 CLI 入口
├── requirements.txt
├── README.md
├── LICENSE
├── docs/cli.md              # CLI 与 JSON 描述格式说明
├── samples/                 # legacy .tim test fixtures
├── edgeweaver/
│   ├── model.py             # 文档模型、行/标签/箭头/时间断裂、600 槽状态
│   ├── tim_format.py        # .tim 读写（counted string、未知字段原样保留）
│   ├── renderer.py          # 与后端无关的绘制逻辑 + QtBackend
│   ├── svg_export.py        # SVG 导出后端
│   ├── emf_export.py        # EMF 导出后端（GDI 记录流）
│   ├── cli.py               # 无窗口 CLI（JSON 生成 / 格式转换）
│   ├── exporters.py         # PNG/PDF/CSV/XML 导出，XML/CSV 导入
│   ├── canvas.py            # 交互画布（绘制、选择、工具、吸附、上下文菜单）
│   ├── dialogs.py           # 添加行、行属性、箭头属性、标注管理
│   ├── mainwindow.py        # 主窗口、菜单、工具栏、文件操作、撤销栈
│   ├── app.py               # 入口
│   └── __main__.py
├── tools/
│   └── emfdump.py           # EMF 头部/记录查看器
└── tests/
    ├── test_tim.py          # 格式/编辑/XML/CSV 回归
    ├── test_render.py       # PNG/SVG/PDF/EMF 导出、Z/斜边几何
    └── test_ui.py           # 无头 UI、箭头吸附、Cycles、属性对话框
```

## `.tim` 格式

```
CString "TIM"
CString "011"                # 010 版本少最后 9 个 int
int32 x4                     # [槽宽 px, 可见槽数, 信号高度 px, 0]
6 x { int32 n; CString[n] }
    list1 行记录（时钟/信号/总线/分隔符）
    list2 标签
    list3/list4 辅助表（样本为空）
    list5 关系箭头
    list6 时间断裂
int32 x9                     # 视图状态
CString x2
int32 x2
N x int32[600]               # flood 填充
N x int32[600]               # delay / 边沿辅助数据
int32 x2
int32 x9 (版本 011)
```

行记录的 600 字符状态串是真正的波形数据：

```
NAME\t\t\t\t\tDATA_0_.<600 chars><attr>
NAME\t\t\t\t\tCLK_0_.<600 chars><attr>
NAME\t\t\t\t\tSEP_0.<separator fields>
```

- 状态字符：`0` 低、`1` 高、`Z` 高阻（画在中间）；总线使用 `2/3/4`。
- 绘制几何：首行顶部 y=20，行距 44 px；波形起点 = 名称列宽 + 5；
  一个状态字符 = 半个时钟槽 = `槽宽` 像素；时钟周期为 2 个槽（50/50）。
- 箭头和时间断裂的 `cycle` 是**边界/边沿索引**（0 表示波形起点），
  位置为 `wave_x0 + cycle * slot_width`。
- 箭头样式取值：`0=Straight, 1=Angled, 2=Bezier, 3=Floating`；未知值按 Bezier 渲染。
- 自由标签的 owner 使用 `EWLabel*N*` 形式；读取时也兼容旧式两字母前缀的 `*Label*N*`。
- 字符串使用 counted-string：长度 <255 用 1 字节，否则 `0xFF` + WORD。
- 中文文本按 GB18030 解码显示；可用 `EDGEWEAVER_TEXT_ENCODING=latin1` 切换西文单字节编码。

### EdgeWeaver 扩展

- **Z 状态字符**：三态高阻。
- **斜边信息**：写入 delay 数组末尾两个单元：
  - `delay[599] = 0x45444745`（`"EDGE"` magic）
  - `delay[598] = 斜边宽度（px）`
  - 其他 delay 数据保持不变；无 sentinel 的行按垂直边沿渲染。
- **箭头像素偏移**：在箭头 tail 末尾追加 `<dx×10>.<dy×10>.EWPIX`。例如
  `0.43.1.0.0.0.10.-100.EWPIX.` 表示箭头整体右移 1 px、上移 10 px。
  没有 `EWPIX` 标记的箭头记录保持原样，按周期/行吸附渲染。
- **边沿间隔测量**：存放在第 3 个辅助字符串表（list3）中，每条以
  `EWM|` 开头、后接 ASCII JSON（`v/src/sc/dst/dc/text/y/dx/color`）。
  `y` 为刻度线绝对高度（缺省=两行中点），`dx` 为水平偏移，`color` 默认
  `#000000`。不含 `EWM|` 的 list3 条目原样保留；文件未修改时仍走原始字节回写。

这些扩展不会改变原有样本的字节级 round-trip；其他工具可能忽略或丢弃它们。

## 测试

```bash
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m unittest discover -s tests -v
```

当前 40 个测试全部通过，包括：

- 4 个真实 `.tim` 的字节级 round-trip；
- EMF 记录结构、头部帧/设备尺寸、Unicode 文本偏移与字体记录；
- 名称/波形分栏线的显示开关、透明背景 SVG 导出；
- 箭头方向键像素微调、撤销与保存/重载；
- 边沿间隔测量：竖线/双向箭头几何、中文文字、颜色/高度/水平偏移、拖动与方向键、
  保存/重载、GUI 工具；
- CLI `draw`/`convert`/`describe`、JSON 结果、错误退出码与多格式输出；
- 编辑/新增行/新增标签/箭头/时间断裂后的保存-重载；
- PNG/SVG/PDF 导出与 2-3-2 的像素级几何检查；
- 箭头选择、弯曲拖动、端点拖动、Delete 删除与撤销恢复；
- 4 种箭头样式的几何、PNG 导出与保存/重载；
- 信号边沿检测与箭头吸附（CEB rising edge 17、SDOUT edge 4）；
- Z 三态绘制与电平（含总线高阻中间线）、斜边/垂直边沿几何、delay sentinel 保存/重载；
- 时钟周期数扩展与时钟参数推断/重载；
- Cycles 数字框、Z 工具、属性对话框接线。

样本目录默认是项目内 `samples/`，可用 `EDGEWEAVER_SAMPLES=/path/to/samples` 覆盖。

## 已知限制

- 几何布局与旧版文件一致，但字体度量因平台而异，**不保证像素级一致**。
- 标签记录中的旋转/角度字段尚未完全解码，当前按水平文本绘制。
- 总线行的边沿仍按总线带渲染；垂直/斜边切换目前只作用于时钟和非总线信号。
- `Cycles:` 以第一路时钟的周期为单位；多时钟且周期不同时以第一路为准。
- 增加 `Cycles` 只重生成时钟；普通信号超出原可见宽度的部分取其 600 槽缓冲中的现有值，
  不会自动填充。
- Z 字符、delay sentinel 和箭头 `EWPIX` 偏移是 EdgeWeaver 扩展；其他工具可能忽略或丢失。
- 打印对话框、剪贴板矢量复制尚未实现；EMF 支持文件导出，但尚未支持把 EMF
  直接复制到系统剪贴板。
- XML 导出遵循 per-signal schema：只包含附着在信号上的标签，自由标签不会写入 XML。
- XML/CSV 导出不包含边沿间隔测量；EMF/SVG/PNG/PDF 与 `.tim` 保存均包含。

## 后续可做

1. 行属性扩展（字体、颜色、Active Low、差分、理想/非理想边沿箭头）。
2. 标签旋转、flood 绘制工具、总线斜边。
3. 打印对话框、剪贴板复制、EMF 剪贴板复制。
4. 与其他时序工具的 SVG/XML 双向互操作。
