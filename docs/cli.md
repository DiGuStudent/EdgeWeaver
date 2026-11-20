# EdgeWeaver CLI

一个无窗口的时序图生成器：读取 JSON 描述，写出 `.tim` / EMF / SVG / PNG / PDF / CSV / XML。
适合脚本和 AI 代理批量出图。

CLI 会自动使用 Qt 的 `offscreen` 平台，不需要图形桌面。

```bash
python3 -m edgeweaver.cli --help
python3 -m edgeweaver.cli describe      # 打印本文档
```

也可以使用仓库根目录的包装脚本：

```bash
./run-cli.sh draw spec.json --out timing.svg
```

---

## 1. 命令

### `draw` —— 从 JSON 描述生成

```bash
python3 -m edgeweaver.cli draw SPEC.json --out OUT.tim --out OUT.svg
```

| 参数 | 说明 |
|---|---|
| `SPEC.json` | JSON 描述文件；`-` 表示从标准输入读取 |
| `--out PATH` | 输出文件，可重复；按扩展名选择格式 |
| `--transparent` | SVG 不写白色背景（透明底） |
| `--png-scale N` | PNG 缩放倍数，默认 `1.0` |
| `--json` | 输出机器可读的结果（路径、字节数、文档尺寸） |

### `convert` —— 转换已有的 `.tim`

```bash
python3 -m edgeweaver.cli convert IN.tim --out OUT.emf --out OUT.png
```

参数与 `draw` 相同，只是输入为 `.tim` 文件。

### `describe`

打印本 Markdown 文档（AI 可以直接运行它来读取用法）。

---

## 2. JSON 描述格式

顶层示例：

```json
{
  "slot_width": 30,
  "slots": 22,
  "signal_height": 16,
  "name_width": 52,
  "rows": [
    {"name": "CLK", "type": "clock", "period": 2, "duty": 0.5, "start_low": true},
    {"name": "DATA", "type": "signal", "state": "0001111100001111"},
    {"name": "BUS", "type": "bus", "state": "2223334444"},
    {"name": "SEP", "type": "separator"}
  ],
  "labels": [
    {"text": "tSU", "x": 120, "y": 60, "owner": "DATA"}
  ],
  "arrows": [
    {"src_signal": "CLK", "src_cycle": 3,
     "dst_signal": "DATA", "dst_cycle": 6,
     "style": "bezier", "offset": 0}
  ],
  "timebreaks": [
    {"signal": "DATA", "cycle": 8}
  ],
  "measurements": [
    {"src_signal": "CLK", "src_cycle": 2,
     "dst_signal": "DATA", "dst_cycle": 8,
     "text": "tSU = 5", "suffix": "ns"}
  ],
  "flood": [
    {"row": 1, "start": 2, "end": 5}
  ]
}
```

### 2.1 顶层字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `slot_width` | int | `20` | 一个半时钟槽（一个状态字符）的像素宽 |
| `slots` | int | `30` | 可见状态字符数，1..600 |
| `signal_height` | int | `16` | 单行高/低电平的像素高度 |
| `name_width` | int | `100` | 左侧名称列宽（px） |
| `version` | string | `"011"` | `.tim` 版本，通常不用改 |
| `rows` | array | 必填 | 行定义 |
| `labels` | array | `[]` | 文本标注 |
| `arrows` | array | `[]` | 关系箭头 |
| `timebreaks` | array | `[]` | 时间断裂 |
| `measurements` | array | `[]` | 边沿间隔测量（竖线 + 双向箭头 + 文字） |
| `flood` | array | `[]` | 高亮填充区间 |

### 2.2 `rows`

| 字段 | 适用 | 说明 |
|---|---|---|
| `name` | 全部 | 行名；不可重复，不能含 `.`、Tab、换行 |
| `type` | 全部 | `clock` / `signal` / `bus` / `separator` |
| `state` | signal/bus/clock | 状态字符串，见下 |
| `period` | clock | 时钟周期（槽数），默认 `2` |
| `duty` | clock | 占空比，默认 `0.5` |
| `start_low` | clock | 是否从低电平开始，默认 `true` |
| `edge` | signal/bus/clock | `ideal`（垂直边沿）或 `slanted`（斜边） |
| `edge_width` | 同上 | 斜边宽度 px，0..40，默认 `6` |
| `dotted` | separator | 分隔线是否虚线，默认 `true` |
| `sep` | separator | 直接指定原始分隔记录（高级用法） |

状态字符：

- `signal`：`0` 低、`1` 高、`Z` 高阻（画在中间高度）
- `bus`：`2` / `3` / `4` 为总线值，`Z` 为高阻，`0`/`1` 也可用
- `clock`：`0` / `1`；若省略 `state`，由 `period`/`duty`/`start_low` 自动生成

`state` 不足 `slots` 位时自动补 `0`（总线补 `4`）；超过 `slots` 的部分不显示，
但会保留在 600 槽缓冲里。

### 2.3 `labels`

```json
{"text": "tSU", "x": 120, "y": 60, "owner": "DATA"}
```

| 字段 | 默认 | 说明 |
|---|---|---|
| `text` | 必填 | 文本；不能含 `.`、Tab、换行 |
| `x`, `y` | 必填 | 文本基线左端坐标（px） |
| `x2`, `y2` | 同 `x`/`y` | 附加锚点（一般不用） |
| `owner` | 自动 | 行名，或自由标签 `EWLabel*N*`；省略时自动生成自由标签 |

### 2.4 `arrows`

```json
{"src_signal": "CLK", "src_cycle": 3,
 "dst_signal": "DATA", "dst_cycle": 6,
 "style": "bezier", "offset": 0, "dx": 0, "dy": 0}
```

| 字段 | 默认 | 说明 |
|---|---|---|
| `src_signal`, `dst_signal` | 必填 | 行名（分隔行不可用） |
| `src_cycle`, `dst_cycle` | 必填 | 0..`slots` 的边界索引（不是槽中心） |
| `style` | `bezier` | `straight` / `angled` / `bezier` / `floating` |
| `offset` | `0` | 弯折/垂直偏移，正负均可 |
| `dx`, `dy` | `0` | 整体像素微调 |

### 2.5 `timebreaks`

```json
{"signal": "DATA", "cycle": 8}
```

在指定行的 `cycle` 边界画双折线断裂符号。

### 2.6 `measurements`

```json
{"src_signal": "CLK", "src_cycle": 3,
 "dst_signal": "DATA", "dst_cycle": 9,
 "text": "tSU = 5", "suffix": "ns",
 "y": 20, "dx": 0, "color": "#000000"}
```

在 A、B 两个边沿之间画两条**虚线**竖线、一条双向水平箭头：空间足够时箭头在
区间内侧、尖端落在刻度线上朝外；区间过窄时箭头移到刻度线外侧、尖端朝内。
箭头上方写文字，竖线覆盖两条信号行（同一行时覆盖该行）；文字支持中文、
英文、数字，单位由 `suffix` 下拉/字段指定。

| 字段 | 默认 | 说明 |
|---|---|---|
| `src_signal`, `dst_signal` | 必填 | 行名（分隔行不可用） |
| `src_cycle`, `dst_cycle` | 必填 | 0..`slots` 的边界索引；两个 cycle 不能相同 |
| `text` | `""` | 箭头上方文字；可含空格、`.`、中文 |
| `suffix` | `""` | 单位后缀：`none`/`""`、`ns`、`µs`、`ms`；也接受 `us` 并规范为 `µs`；显示为 `text + 空格 + suffix` |
| `y` | 自动 | 水平刻度线的绝对 y（px）；省略时位于两行中点；建议 >= 16 以免文字超出画布 |
| `dx` | `0` | 整体水平像素偏移 |
| `color` | `#000000` | 竖线/箭头/文字颜色；任意 CSS/QColor 名称或 `#RRGGBB` |

`y` 高于信号行时竖线向上伸长，低于时向下伸长；GUI 中可用 Select 工具上下拖动，
或选中后按方向键 1 px（Shift 10 px）调整。

### 2.7 `flood`

```json
{"row": 1, "start": 2, "end": 5, "value": 1}
```

`row` 可以用行下标或行名；`start`/`end` 为槽区间（左闭右开）；
`value` 非 0 即填充浅黄色背景。

---

## 3. 坐标与布局

所有坐标都是 96 dpi 像素，与 SVG/EMF 输出一致：

- 第 `i` 行顶部：`y = 20 + i * 44`
- 波形起点：`x0 = name_width + 5`
- 第 `s` 个槽的 x：`x0 + s * slot_width`
- 内容尺寸：宽 `x0 + slots * slot_width + 24`，高 `20 + 行数 * 44 + 24`

箭头和时间断裂的 `cycle` 是**边界索引**：0 表示波形起点，
`cycle_to_x(cycle) = x0 + cycle * slot_width`。

---

## 4. 输出格式

`--out` 的扩展名决定格式，可一次写多个：

| 扩展名 | 格式 | 备注 |
|---|---|---|
| `.tim` | legacy 时序文件 | 版本 011 |
| `.emf` | Enhanced Metafile | 矢量，白色背景 |
| `.svg` | SVG | `--transparent` 可去背景 |
| `.png` | PNG | `--png-scale` 控制分辨率 |
| `.pdf` | PDF | 页面尺寸=图片尺寸 |
| `.csv` | CSV | 每行信号 + 各槽值（不含测量） |
| `.xml` | Timing XML | 与导入格式一致（不含测量） |

示例：

```bash
python3 -m edgeweaver.cli draw spec.json \
  --out timing.tim --out timing.emf --out timing.svg --transparent \
  --out timing.png --png-scale 2 --json
```

`--json` 输出示例：

```json
{"ok": true,
 "document": {"rows": 4, "slots": 22, "slot_width": 30, "signal_height": 16,
              "name_width": 52, "content_width": 741, "content_height": 220,
              "measurements": 1},
 "outputs": [{"path": "timing.svg", "format": "svg", "bytes": 17123}]}
```

---

## 5. 完整示例

### 5.1 时钟 + 数据

```json
{
  "slot_width": 30,
  "slots": 16,
  "signal_height": 16,
  "name_width": 60,
  "rows": [
    {"name": "CLK", "type": "clock", "period": 2, "duty": 0.5},
    {"name": "DATA", "type": "signal", "state": "0001111100001111"}
  ]
}
```

```bash
python3 -m edgeweaver.cli draw spec.json --out demo.svg --out demo.emf
```

### 5.2 总线、标注、箭头、时间断裂

```json
{
  "slot_width": 30,
  "slots": 22,
  "signal_height": 16,
  "name_width": 64,
  "rows": [
    {"name": "CLK", "type": "clock", "period": 2},
    {"name": "DATA", "type": "signal", "state": "0001111100001111000000",
     "edge": "slanted", "edge_width": 6},
    {"name": "ADDR", "type": "bus", "state": "2223334444222333444422"},
    {"name": "SEP", "type": "separator", "dotted": true}
  ],
  "labels": [
    {"text": "tSU", "x": 120, "y": 64, "owner": "DATA"},
    {"text": "valid", "x": 300, "y": 150}
  ],
  "arrows": [
    {"src_signal": "CLK", "src_cycle": 3, "dst_signal": "DATA",
     "dst_cycle": 6, "style": "bezier", "offset": -20},
    {"src_signal": "DATA", "src_cycle": 8, "dst_signal": "ADDR",
     "dst_cycle": 10, "style": "angled", "dx": 3, "dy": -2}
  ],
  "timebreaks": [{"signal": "DATA", "cycle": 16}],
  "measurements": [
    {"src_signal": "CLK", "src_cycle": 3,
     "dst_signal": "DATA", "dst_cycle": 9,
     "text": "tSU = 5", "suffix": "ns"}
  ],
  "flood": [{"row": "ADDR", "start": 2, "end": 6}]
}
```

---

## 6. 错误与退出码

- `0`：成功
- `1`：描述/文件/导出错误（stderr 输出 `error: ...`）
- `2`：命令行参数错误（argparse）

常见错误：行名重复、箭头或时间断裂引用了不存在的信号、
状态字符不合法、`start >= end`、输出扩展名不支持。

---

## 7. 给 AI 的使用建议

1. 先运行 `python3 -m edgeweaver.cli describe` 读取本说明（或直接读 `docs/cli.md`）。
2. 写 JSON 时先确定 `slots` 与 `slot_width`，再按 `cycle` 边界放置箭头/断裂。
3. 需要办公软件可直接嵌入的矢量图时导出 `.emf`；需要透明底矢量图时用 `.svg --transparent`。
4. 需要检查结果时用 `--json` 获取文档尺寸和输出字节数。
5. CLI 不修改输入 `.tim`；`convert` 只读取。
