# DroneHacks Flight Forensics & Replay Workbench

仅用于离线或飞行后取证。输入是已经落盘的日志，输出始终 `executed=False`。
本模块不导入飞控连接、指令适配器或规划器，不需要连接无人机。
本次实现与示例只验证 synthetic fixtures，尚未用真实 `.ulg` 验证实际 PX4 行为。

新增的四流 OAK/PX4/VL53L1X/advisory 契约、独占封存和无硬件 preflight 见
[integration-replay.md](integration-replay.md)。已刷新 B/D handoff 的后续桥接方案见
[integration-plan.md](integration-plan.md)。局部感知平面不代表完整三维通行；
所有报告固定 `full_3d_traversability=UNKNOWN`、`supports_3d_traversal=false`。

## 安装与 CLI

在当前 forensics worktree 根目录运行，Python 3.12 已验证。
依赖仅安装到当前 worktree 的 `.venv`；不需要 sudo、全局安装或 OpenCV。
`PYTHONPATH=src` 允许直接运行源码，无需安装主项目的视觉依赖。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-forensics.txt
PYTHONPATH=src .venv/bin/python -m aegisland.forensics --help

# Fixtures are generated into ignored run storage; binary fixtures are not committed.
PYTHONPATH=src .venv/bin/python -m aegisland.forensics fixtures \
  --output runs/forensics-fixtures

# 有回退与异常的 synthetic 示例：对齐为 unknown。
PYTHONPATH=src .venv/bin/python -m aegisland.forensics report \
  --px4 runs/forensics-fixtures/synthetic.ulg \
  --jetson runs/forensics-fixtures/jetson.jsonl \
  --output runs/forensics-demo

# 有配对时钟证据的 synthetic 示例：仅在锚点区间内给出 inferred 估计。
PYTHONPATH=src .venv/bin/python -m aegisland.forensics report \
  --px4 runs/forensics-fixtures/aligned.ulg \
  --jetson runs/forensics-fixtures/aligned-jetson.jsonl \
  --alignment runs/forensics-fixtures/alignment.json \
  --output runs/forensics-aligned

.venv/bin/python -m pytest tests/test_forensics.py
.venv/bin/ruff check src/aegisland/forensics tests/test_forensics.py
```

完整项目安装时可用可选依赖 `.[forensics]`，入口为 `dronehacks-forensics`；
最小环境使用上面的模块入口。CLI 没有 `--execute`、串口、UDP、飞控地址或安全参数选项。

输出目录包含：

| 文件 | 内容 |
| --- | --- |
| `report.html` | 自包含本地页面；按源/实例选择、逐条滑动、原始时间轴与发现筛选；无 CDN、请求或服务端依赖 |
| `summary.json` | 输入 SHA-256、解析完整性、规则覆盖、阈值、发现、诊断样本与对齐证据 |
| `findings.md` | 可人工复核的 finding ledger，包含输入哈希、记录引用、分类和限制 |

用浏览器直接打开 `report.html` 即可离线回放。回放显示已记录的诊断数值，
不回放任何飞行指令。HTML 的数据与表格在禁用 JS 时仍可查看，滑块交互需要 JS。
输入和时钟证据文件不能被同名报告覆盖；已有报告可重新生成。
summary 中的原生整数时间戳同时带有 `timestamp_text` 十进制字符串；
浏览器用该字符串和 BigInt 绘制，避免纳秒时间超过 JavaScript 安全整数范围后的精度损失。

退出码：`0` 为两个输入均可完整解析（可以仍有异常或对齐 unknown）；
`2` 为缺少输入、空输入、损坏、缺字段或未知测量导致不完整，仍生成报告；
`1` 为配置错误或报告写入失败。CLI 最后一行 stdout 是简要 JSON。
仅提供一个日志、甚至完全没有日志时也可生成 unknown 报告；`0` 不表示飞行安全。

## Jetson perception JSONL v1

正式契约：[jetson-perception.schema.json](jetson-perception.schema.json)。
一行一个 JSON 对象，UTF-8；以下字段均必需，`tracking_valid` 可选。
严格拒绝重复键、非有限数值、错误类型和未定义字段。
损坏行被隔离并保留原始行号，后续有效行仍可分析。

| 字段 | 类型与单位 | 含义 |
| --- | --- | --- |
| `schema_version` | 整数 `1` | 契约版本 |
| `clock` | `jetson_monotonic_ns` | 本机单调时钟域；不能当成 UTC 或 PX4 boot time |
| `timestamp` | 非负整数，纳秒 | 该记录对应帧的采样时刻，生产者须统一使用同一单调时钟 |
| `frame_id` | 非负整数 | 同一采集会话中的帧序号 |
| `depth_coverage` | `[0,1]` 或 `null` | 指定 ROI 内有效深度覆盖比例 |
| `invalid_depth_ratio` | `[0,1]` 或 `null` | 指定 ROI 内无效深度比例；ROI 须由生产者保持一致 |
| `line_confidence` | `[0,1]` 或 `null` | 线跟踪置信度 |
| `obstacle_distance_m` | 非负有限数或 `null` | 米；`null` 表示未知，不代表没有障碍 |
| `mode` | 非空字符串，至多 256 字符 | 生产者记录的感知模式，不下发模式切换 |
| `decision` | 非空字符串，至多 256 字符 | 已记录的决策文字，仅作证据显示 |
| `latency_ms` | 非负有限数或 `null` | 生产者报告的帧端到端延迟，毫秒 |
| `dropped_frame` | 布尔值 | 当前记录是否由生产者标记为掉帧；不当作累计计数 |
| `source_hashes` | 非空对象，值为小写 64 位 SHA-256 | 生产者声称关联的帧、模型、配置等源哈希 |
| `executed` | 只能为 JSON `false` | 不可突破的分析接口边界 |
| `tracking_valid` | 可选布尔值 | 显式跟踪有效性；缺省时不能声称观测到跟踪丢失 |

整数上限为 `2^63-1`；距离和延迟上限为 `1e12`。未知测量必须显式为 `null`，
不能伪造零、NaN 或 Infinity。`null` 记录仍可用于其他字段分析，但该输入会标记不完整。
`source_hashes` 是生产者声明；工具实际计算的是输入文件字节哈希和时钟证据哈希。
仅提供哈希并不证明帧来源或模型版本真实。

## PX4 ingestion 与可用字段

解析器固定为 PyULog 1.2.2。先做 ULog 头、记录长度和最小结构检查，
再用 PyULog 解析白名单 topic。截断尾部可恢复完整前缀，但始终标明损坏与不完整。
PyULog 解析失败、版本不受支持、字段缺失和非有限数值都会进入 ledger。
未知的 topic 不会被解释为正常状态。

| Topic | 分析字段 | 限制 |
| --- | --- | --- |
| `vehicle_local_position` | `xy_valid`, `z_valid`, `v_xy_valid`, `v_z_valid` | 无效标志只说明记录中的估计状态，不确定原因 |
| `vehicle_status` | `nav_state`, `failsafe` | 保留模式原始编号，不猜测固件版本对应的名称或 failsafe 原因 |
| `actuator_motors` | `control[0..11]` | 归一化电机请求；不解释旧版 PWM `actuator_outputs` |

每个 topic 的 `multi_id` 独立分析，原始样本顺序不重排。
PX4 时间使用 `timestamp` 的 boot 微秒；它与 Jetson 纳秒不能直接比较。
不提取位置、航点、地图、轨迹或参数。ULog dropout 是日志丢失，不能当成摄像头掉帧。
电机字段的 NaN 在 PX4 中可表示停止/未使用输出；工具仍将该数值标为 unknown，
不会当成饱和或默认零，也不会据此宣称日志本身损坏。

## 时间对齐契约

没有配对时钟证据，状态为 `unknown`，映射值为 `null`。
不使用首帧时间、模式变化相似性、墙上时钟或观察到的异常来猜偏移。

`--alignment` 读取一个本地 JSON descriptor（见 fixtures 中 `alignment.json`）：

```json
{
  "schema_version": 1,
  "executed": false,
  "method": "paired-clock-observation",
  "source_hashes": {"px4": "<input SHA-256>", "jetson": "<input SHA-256>"},
  "evidence_file": "sync-evidence.jsonl",
  "evidence_sha256": "<evidence file SHA-256>"
}
```

证据文件路径相对 descriptor。每行是同一可识别事件的时钟对：

```json
{"event_id":"paired-event-1","px4_boot_us":1000000,"jetson_monotonic_ns":9000000000,"uncertainty_us":100}
```

需至少两个唯一事件、两个时钟严格递增、两个输入完整且没有检测到回退，
输入和证据哈希均吻合。以首尾锚点作仿射插值；漂移绝对值不得超过 2000 ppm，
最大锚点残差加声明不确定度不得超过 5000 微秒。映射只存在于首尾 Jetson 锚点区间。
报告保留 descriptor 与证据字节哈希、锚点、漂移和条件不确定度。

通过这些检查的映射仍为 **`inferred`**，依赖配对观察的真实性和区间内仿射时钟假设；
哈希只证明使用了哪些字节，不能独立证明物理同步。物理同步结论仍为 `unknown`。
无证据、冲突、回退、文件损坏、锚点区间外均不会给出已证实对齐结论。
一个流的时间戳回退足以使整次跨源映射 unknown；工具不自动拼接启动 epoch。
回退后不跨 epoch 比较模式或帧号。

## 自动标记与证据层级

| 发现 | 分类 | 触发规则 |
| --- | --- | --- |
| estimator invalid | observed | 已记录的任一 local-position validity 标志为 false |
| tracking loss | observed / inferred | 显式 `tracking_valid=false` / 线置信度低于 0.3 |
| 深度空洞候选 | inferred | 覆盖率低于 0.5 或无效比例高于 0.5 |
| 掉帧 | observed / inferred | 生产者掉帧标志 / 同一可比较 epoch 中帧号有缺口 |
| 延迟尖峰候选 | inferred | 记录延迟大于 100 ms；不是工具独立测量 |
| 模式切换 | observed | 同一流相邻记录的 `mode` 或 `nav_state` 改变 |
| failsafe | observed | `vehicle_status.failsafe=true`；原因与实际响应未知 |
| 控制饱和候选 | inferred | 有限归一化电机请求绝对值达到 0.95；不是物理饱和证明 |
| 时间戳回退 | observed | 同一流源顺序中的 timestamp 减小；原因未知 |

阈值仅为离线复核设置，CLI 可修改分析阈值；这些设置不写入飞控。
`--depth-coverage-min`、`--invalid-depth-ratio-max`、`--line-confidence-min`、
`--latency-ms-max`、`--saturation-abs-min` 会记录进 summary 与报告。
缺少字段不补零、不推断健康；coverage 表示规则是否存在可用输入，不代表完整时间覆盖。
多条持续异常按样本列出，不擅自合并为一次事故。

## 实现范围与验证限制

全部日志先读入内存形成哈希快照，再解析相同字节；HTML 内嵌诊断样本。
当前实现面向小到中型飞行后记录，未做超大日志流式处理或浏览器性能基准。
未验证所有 PX4 固件版本、ULog 崩溃附加数据、真实 Jetson 时钟漂移或物理执行行为。
异常记录不能定位根因；旧版/缺失 topic 的规则覆盖会是 unknown。

参考实现依据：[PyULog 官方仓库](https://github.com/PX4/pyulog)、
[PX4 ULog 文件格式](https://docs.px4.io/main/en/dev_log/ulog_file_format)、
[VehicleStatus 定义](https://github.com/PX4/PX4-Autopilot/blob/main/msg/versioned/VehicleStatus.msg)、
[ActuatorMotors 定义](https://github.com/PX4/PX4-Autopilot/blob/main/msg/versioned/ActuatorMotors.msg)。
字段支持范围以本工具白名单和输入自身定义为准，主分支文档不作为固件版本证明。

数据使用边界见 [competition-data-boundary.md](../competition-data-boundary.md)。
