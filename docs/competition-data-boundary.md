# DroneHacks competition data boundary

Flight Forensics & Replay Workbench 只做离线或飞行后的只读取证分析。
本次交付只使用明确标记的 synthetic 数据，未验证真实 PX4 行为。

## 输入与证据

输入限于本地 PX4 `.ulg`、Jetson perception JSONL，以及已有的配对时钟证据。
工具不连接无人机、不读取串口或遥测 socket、不启动 MAVLink/MAVSDK/PX4 连接，
不发送命令、模式请求、setpoint、任务或参数写入。
本工具不提供实时监控功能；笔记本如用于现场工作，仅允许只读监控与证据分析。

输入文件按字节计算 SHA-256，解析使用同一快照；JSONL 的 `source_hashes`
仍是生产者声明，不能当成独立来源认证。缺字段、损坏、乱序、非有限数值、空输入和
无法证明的时钟关系均需显式暴露。`observed` 仅表示日志记录了该值，
`inferred` 表示依据规则或模型推断，`unknown` 表示证据不足。
观察到 failsafe 标志不等于证明其触发原因或真实执行结果。

## 不可突破的 executed 边界

API、CLI、摘要、HTML 内嵌数据与 ledger 均固定 `executed=False`。
不存在执行开关或可配置的执行适配器。Jetson 输入中的 `executed` 必须是 JSON `false`；
`true`、数字零和缺失均拒绝该记录，并标记不完整，不能静默改写后接收。
日志中的 `decision`、`mode` 与电机请求只是历史证据文字或数值，不能转换成指令。

forensics 模块独立于仓库现有规划、仿真执行和飞控连接模块。
测试检查其依赖边界、不可设置的 `executed` 属性与输出中的固定 false，
以防分析流程误接入控制路径。这些检查不代表对仓库其他模块的飞行安全认证。

## 安全设置

不得修改 failsafe、kill switch、geofence、电池安全参数或其作用边界。
CLI 只接受离线复核阈值，不写入任何飞控参数。
分析发现只能供人工审阅，不能自动触发飞机动作或修改现场安全配置。

## 局部感知平面与三维边界

深度/间隙只覆盖声明的局部相机探测平面与采样 ROI。即使
`local_plane_supported=true`、传感器读数一致或下降几何条件通过，
`full_3d_traversability` 始终为 `UNKNOWN`，`supports_3d_traversal` 始终为 `false`。
ROI 外、探测平面外、遮挡体积、整机扫掠体积和动态障碍均未评估。
不得把旧字段 `supported` 或局部宽度解释成穿行、下降、着陆或执行许可。
所有嵌套感知平面均保留这些限制，录证器拒绝提升三维通行或执行权限的记录。

## 单次飞行数据的使用范围

某次练习或比赛飞行的数据、地图和轨迹，不能被本工具导出成后续飞行的直接输入。
不提供航点、路线、地图、位置轨迹、mission、setpoint、控制策略或飞控参数导出接口。
ULog 只提取诊断白名单字段，不将位置/地图字段放入 summary 或回放页面。
报告中的“回放”是诊断证据逐条查看，不是飞行指令重放。

报告、finding ledger 和哈希只能作为该次飞行的解释与审计材料。
禁止将报告诊断样本接入后续飞行的规划器、控制器或飞控上传流程。
工具不自动上传、发布或分享日志、报告、练习场地信息或比赛数据。
HTML 自包含，没有外部脚本、地图瓦片、CDN、网络请求或隐式采集。

## 本地安装与操作

唯一实现 checkout 是当前 forensics worktree。
新增 Python 依赖仅安装到该 worktree 的 `.venv`；不 sudo，不全局安装。
报告写到显式指定的本地目录，输入文件与时钟证据不允许被报告覆盖。
synthetic fixtures 可复现生成，已有不同内容的文件会被拒绝覆盖。
