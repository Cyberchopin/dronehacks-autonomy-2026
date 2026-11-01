# DroneHacks 离线感知原型

本原型只读合成图像或本地 NPZ 录制帧，输出 advisory/perception evidence。入口是
`CoursePerception.observe(OfflineFrame)`；本地回放入口是 `python -m aegisland.course_replay`。
输出始终包含 `control_output=DISABLED`、`command_executed=false` 和 `advisory_only=true`。
硬化后的结果 schema 为 `aegisland.course-perception.v2`，另有显式 `executed=false`、
`authority_change=NONE`；`capabilities` 将 window/return navigation 标为 unimplemented，
metric VIO/SLAM 标为 not_provided。
代码没有连接 planner、PX4、MAVLink、相机采集器或命令执行器。

实现顺序与 checkpoint 的对应关系如下。checkpoint 名称只用于解释用途，没有进入推理条件。

| 优先级 | 用途 | 本次交付的证据 | 边界 |
| --- | --- | --- | --- |
| 1 | 第一走廊、迷宫地面线 | `line`：连通区域、逐行覆盖、宽度、分支/竞争检查、归一化采样点、置信度与拒绝理由 | 不判断岔路方向；横向线、断线和遮挡可能拒绝 |
| 2 | Gate A 出口 | `openings`：矩形开口候选、ROI、形状置信度、每个候选的深度/间隙证据 | 不区分出口、窗户和墙上矩形；`exit_identity=unverified` |
| 3 | 黑暗 tunnel | `low_light`、`depth`：原始亮度、CLAHE 前后对比度和线路得分、深度年龄/错时/退化理由 | 低光状态始终 `degraded`；恢复线路也不提高控制权限 |
| 4 | Gate B / chicane | `clearance`：连续可观察列、归一化列区间、探测平面宽度、需求宽度及拒绝理由 | 不规划绕行顺序；不证明整机扫掠体积可以通过 |
| 5 | landing pad | `landing`：外圈/内孔、形状置信度、局部深度、平面残差/倾角、内圈尺寸代理、下降几何适宜度及拒绝理由 | 不证明身份、动态安全或可着陆性 |
| 6 | window / return | 未实现独立逻辑 | 不参与基本路线的状态切换 |

复用了现有 OpenCV 管线中的灰度/轮廓处理方式和 CLAHE。新增的 `clahe_gray` 是从既有
`OpenCVLandingPerception.observe` 抽出的相同操作，保留原参数和旧管线行为。复用
`sector_report` / `SectorConfig` 作为深度证据，`ZoneCandidate.bbox_xywh` 作为候选 ROI
结构，`stage_timing.Collector` 记录阶段耗时，`JsonlTraceStore` / `jsonable` 保存本地证据。
本地 trace store 现在也接受 mapping，不必伪造 telemetry、decision 或 command。

输入契约为：BGR `uint8[H,W,3]`；可选 optical-axis z 深度 `float[H,W]`，单位米；同形状
`bool` validity mask；对应这张对齐图的 `Intrinsics(fx,fy,cx,cy)` 和 `calibration_id`。
像素坐标向右/向下，camera z 向前。图像、深度和回放评估时间必须使用同一个时钟域的整数
纳秒。`evaluated_at_ns` 是回放时明确指定的评估时间，不能拿现在的墙钟与历史采集时间相减。
`camera_view` 必须显式为 `forward` 或 `downward`，不从 checkpoint 推测安装朝向。
声明朝向和 calibration ID 不能代替实际标定；调用者负责提供真实的对齐结果。

`OfflineFrame` 只接受 `source_type=synthetic|recording` 和非空 `source_id`。没有深度时仍能输出
视觉候选，间隙与下降几何适宜度均拒绝。格式不合法时抛出 `ValueError`；质量退化时保留
证据并输出理由，不补造深度。输入数组不会被修改。每帧保存数组内容 SHA-256、来源、标定 ID、
配置完整快照与其 SHA-256；报告保存 Python/OpenCV/NumPy、Git HEAD/dirty 状态和源码哈希。

状态只描述当前观察：`line_supported`、`opening_candidate`、`pad_candidate`、`degraded`、
`unobservable`。低光或整体深度失效优先成为 `degraded`；否则按 pad/opening/line 是否存在
候选选择状态。候选状态允许带拒绝理由，例如 pad 被检测到但平面不合格。没有任务阶段计数、
waypoint、绝对比赛时间或固定比赛像素坐标。模块逐帧独立，不保留路线进度，也不推断完成穿门。

线路在归一化的下部 ROI 中按相对中值对比度提取亮线或暗线。硬化后要求至少 70% 行覆盖、
足够行数、近场端点支持、稳定宽度、较小中心线拟合残差，以及侧边裁切/上部墙沿连续性
检查。拟合剔除明显比中值宽的转角行，避免把 L 形转角的水平部分当作路径中点。
`candidate_confidence` 保留行覆盖率乘以对比度饱和得分；`confidence` 还乘以拟合一致性得分。
几何失败或候选竞争时有效 confidence 为零、采样点为空，状态为 ambiguous/unknown。
几何通过但证据强度不足时保留低分诊断，不输出路径点。只有 `detected=true` 才有路径采样点；
仍需读取 `rejection_reasons`。所有分数都是启发值，不是正确概率；semantic_identity 仍为
unverified。强曲率真实路径、从侧面进入的地面线和占满整个上部图像的真线可能被保守拒绝。

低光判据检查原始平均亮度和暗像素比例。只有原始图像低光才执行同帧 CLAHE；记录实际
标准差变化和线路得分变化。只有两项增益达标且线路通过自身检测，才标记 `line_recovered`。
均匀黑图不会因为 CLAHE 输出变亮而被标成恢复。恢复仅替换线路证据，外圈/开口仍用原图；
低光始终拒绝下降几何适宜度。独立且有效的深度仍可提供局部距离证据，`authority_change`
始终为 `NONE`，不产生任何权限升级或控制意图。

整体深度有效性要求图像和深度年龄均合格、图深同步合格、现有扇区报告的全部扇区有效。
扇区报告的距离是沿射线的 Euclidean range；局部 clearance/landing 则用 optical-axis z。
保留共享报告的原始 `frame_valid_fraction`，它只说明原始可用回波占比，不等于局部可测范围
内深度占比。局部证据另外过滤近距盲区、非有限数、零值和配置量程以外的深度；即使共享
报告给出 clear-to-max-range，超量程值在局部也作为未知。过期/未来/错时数据不输出可信宽度。

间隙在候选 ROI 内收边后，逐列检查整个垂直观察区域：出现一个未知或探测平面之前的像素，
该列就不能作为空闲列。不使用低分位数抹掉小障碍物。最长连续列数乘以 `probe_z/fx` 得到
`width_at_probe_m`，并与 `envelope_width_m + 2*clearance_margin_m` 比较。这是在相机 z 探测
平面的投影宽度和列区间；不等于真实门洞的三维宽度、到障碍物的侧向净距、整条 tunnel 的
安全性或可执行路径。看不到的 ROI 外部没有空闲结论。

v2 的每一个 gap（包括 opening 内嵌 gap）明确包含：

```text
scope = "local_camera_z_probe_plane"
supported_meaning = "observed_local_plane_width_only"
local_plane_supported = true | false
full_3d_traversability = "UNKNOWN"
supports_3d_traversal = false
authority_change = "NONE"
executed = false
sampled_bbox_normalized = 实际内收采样区域
unassessed = ROI 外部、探测平面以外、遮挡体积、机体扫掠体积、动态障碍
```

`supported` 是 `local_plane_supported` 的兼容别名，绝不能解释为全三维可通行。
新消费者应检查 schema/scope 并读取显式局部字段。可见紧凑 RGB 结构若对应平坦远深度，
可能是涂装，也可能是深度配准/测量失效；当前保守输出 `rgb_depth_conflict_suspected`，
宽度和列区间置空。该检查保留 ROI 外的图像/深度背景作为参照，避免内嵌候选裁掉视觉阻挡物
上下文后被误当成新开口。视觉开口对应近距深度时标记 visual_aperture_not_confirmed_by_depth。
这些只是有限的冲突代理，`rgb_depth_consistency` 从不宣称完整配准验证。

落点先检查亮/暗两种极性的外轮廓和内孔，要求足够圆、不过度椭圆、内外中心接近。拒绝
实心圆、矩形、明显椭圆、裁切外圈和竞争外圈。置信度是 circularity × axis ratio，存在可测
深度时再乘局部有效比例；检测置信度与下降几何适宜度分别输出。下降几何适宜度还要求
向下视图、深度新鲜同步、内孔局部深度充足、距离合格、内圈米制尺寸代理足够大、平面残差
和相对光轴倾角合格。拟合最多采样配置数量的点，残差检查覆盖全部有效内孔点，防止漏掉
小侵入物。倾角相对相机光轴，不能解释为相对重力倾角。

`descent_geometry_suitable=true` 仅表示这些静态观测条件通过。运动、语义 pad 身份、重力
对齐、完整机体足迹和接地动力学列在 `unassessed`。复用的 `ZoneCandidate.safe` 始终为
false，`motion_occupancy/texture_risk/appearance_occupancy=1`、`clearance=0` 是未评估项的
保守占位，不能作为实际测量。这些未知项不会被旧 landing planner 意外当成 safe candidate。

全部新检测阈值集中在 [course_config.py](../src/aegisland/course_config.py)，共享深度默认值
由嵌套 `SectorConfig` 提供并完整序列化。默认 provenance 是 synthetic-v2-adversarial 工程启发值，
没有现场标定。自定义 JSON 必须声明 provenance；未指定字段使用记录在最终快照中的默认值。
默认关键阈值如下，完整值见 [当前配置](../examples/course-perception-hardened/config.json)。

| 项目 | 默认值 |
| --- | --- |
| line ROI / 对比度门限 / 满分对比度 / 接受分数 | 下部 65% / 18 / 80 灰度级 / 0.55 |
| line 几何支持 | 行覆盖 ≥ 0.70、至少 8 行；拟合 rms ≤ 0.012 图宽、最大误差 ≤ 0.035 图宽 |
| line 端点/宽度/墙沿检查 | 底部距离 ≤ 0.08 图高；侧边距 > 0.01 图宽；width CV ≤ 0.40；上部连续性 ≤ 0.50 |
| RGB/深度冲突代理 | 面积 ≥ 0.02 ROI、双轴范围 ≥ 0.15 ROI、填充率 ≥ 0.65；远深度内外差 ≤ 0.08 m |
| low-light / CLAHE / 恢复增益 | mean < 40 或暗比例 ≥ 0.75；clip 2.2、8×8；std 增益 ≥ 5 且 line 增益 ≥ 0.05 |
| 图/深度年龄 / 同步偏差 | ≤ 200 ms / ≤ 25 ms；未来时间拒绝 |
| 局部深度比例 / 样本数 | ≥ 0.90 / ≥ 50；空闲列要求所有像素已知且足够远 |
| 探测平面 / envelope / 单侧 margin | z=2 m / 0.35 m / 0.15 m，需求宽度 0.65 m |
| 外圈 circularity / axis ratio / landing 分数 | ≥ 0.84 / ≥ 0.65 / ≥ 0.65 |
| landing 深度 / 平面残差 / 光轴倾角 | 0.4–4 m / 最大 0.04 m / 最大 15° |

这些参数不能当作比赛硬件安全尺寸。尤其是 envelope、相机标定、曝光、安装姿态和视场裁剪，
必须用实际录制数据重新检查并记录新的 provenance。

离线回放示例：

```bash
PYTHONPATH=src <main-checkout>/.venv/bin/python -B \
  -m aegisland.course_replay --adversarial --output runs/course-review-new
```

这里借用既有环境的解释器，代码来自当前 worktree；没有修改其他 checkout 或环境。输出目录
必须不存在，生成 `trace.jsonl`、`report.json`、`report.md` 和 `config.json`。阶段耗时复用
Collector；整帧 `processing_ms` 从输入检查计到证据构造，包括输入哈希及阶段记录，不含磁盘
写出。首次冷启动样本也计入单次回放；这些 CPU 数字不能外推到 Orin 或真实飞行频率。

本地录制输入使用 `--recording frame-001.npz frame-002.npz`。每个 archive 的键为：

```text
image: uint8[H,W,3] (BGR)
timestamp_ns, evaluated_at_ns: scalar integer
camera_view: scalar Unicode "forward" or "downward"
# 以下深度组要么全部提供，要么全部省略：
depth_m: float[H,W] (aligned camera-z metres)
depth_valid: bool[H,W]
depth_timestamp_ns: scalar integer
intrinsics: float[4] = [fx,fy,cx,cy]
calibration_id: scalar Unicode
```

加载器禁用 pickle，不推测采集时间、朝向或内参。测试中的 NPZ 是合成帧的保存/加载验证，
没有在本次新增实验中冒充真实相机录制。当前实际结果与残留失败见
[generality-defense.md](generality-defense.md) 和 [硬化报告](../examples/course-perception-hardened/report.md)。
`examples/course-perception` 保留为初版 v1 历史证据，其源码哈希和行为不代表硬化后的代码。
