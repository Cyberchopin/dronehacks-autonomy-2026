# 上游 GPS-denied 方法证据矩阵

审计日期：2026-10-31（America/Los_Angeles）；小文件取回日期：2026-11-01 UTC。母仓库基线 `e13b698`。本次只做源码、文档和公开接口审计；没有使用 REA，没有编译或执行第三方实现。所有结论限定于下列版本。

`GO` 表示明确限定用途可继续；`CONDITIONAL` 表示存在列出的交付门槛；`NO-GO` 表示当前禁止进入比赛交付。源码可读、许可可用、硬件可运行、允许重分发分别判断。许可证与 NOTICE 详见 [许可证审计](license-and-redistribution-review.md)，实施选择见 [集成决策](integration-decision.md)。

## 固定版本与结论

| 候选 | 固定 tag / 完整 commit | 官方证据 | 当前结论与适用范围 |
| --- | --- | --- | --- |
| nvidia-isaac/cuVSLAM | `v17.0.1` / `51631ba358ea51262342f9ae649820d639363eb9` | [固定源码](https://github.com/nvidia-isaac/cuVSLAM/tree/51631ba358ea51262342f9ae649820d639363eb9)；[发布页](https://github.com/nvidia-isaac/cuVSLAM/releases/tag/v17.0.1)；[许可证](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/LICENSE) | **CONDITIONAL**：主 VO/VIO 候选；限定 NVIDIA 平台；具体发布包与目标机尚未核验。 |
| NVIDIA-ISAAC-ROS/isaac_ros_visual_slam | `v5.0-0` / `9058506efd0b967ac894a717bdbe98df017637e5` | [固定 README](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/9058506efd0b967ac894a717bdbe98df017637e5/README.md)；[package.xml](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/9058506efd0b967ac894a717bdbe98df017637e5/isaac_ros_cuvslam/package.xml)；[Apache 许可证](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/9058506efd0b967ac894a717bdbe98df017637e5/LICENSE) | **CONDITIONAL**：可选 ROS 接口；包名已为 `isaac_ros_cuvslam`，接口包仍为 `isaac_ros_visual_slam_interfaces`。不据此批准整个栈为 Apache-2.0。 |
| EuRoC MAV | 数据标识 DOI `10.3929/ethz-b-000690084`，ETH 记录日期 `2024-09-27`；官方说明页 commit `0ee434728bf1f13a14f86937baf53edd30ea556a` | [固定说明源码](https://github.com/ethz-asl/ethz-asl.github.io/blob/0ee434728bf1f13a14f86937baf53edd30ea556a/_datasets/euroc_mav.md)；[ETH 数据记录](https://www.research-collection.ethz.ch/items/bcaf173e-5dac-484b-bc37-faf97a594f1f)；[DOI](https://doi.org/10.3929/ethz-b-000690084) | **CONDITIONAL**：非商业离线评估候选；实际数据版本/字节哈希及比赛使用范围待关闭。数据本身没有可填写的 Git tag。 |
| luxonis/depthai-core / 官方 OAK-D 示例 | `v3.11.0` / `e9ead6536e1bf9842d91211fcf80f0b4ef119954`；示例与库同一 commit | [MIT 许可证](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/LICENSE)；[双目示例](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/examples/python/StereoDepth/stereo.py)；[固件条款](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/notices/depthai-device-RVC2-LICENSE) | **CONDITIONAL**：MIT 主机代码/示例的接口参考为 **GO**；OAK 运行与发行包须核准设备固件和实际依赖。 |
| NVlabs/Fast-FoundationStereo | `476f4249561f7c79ca707326954f9255643412a6`（审计时 master 的固定快照；未选择权重版本） | [许可证](https://github.com/NVlabs/Fast-FoundationStereo/blob/476f4249561f7c79ca707326954f9255643412a6/LICENSE.txt)；[模型卡](https://github.com/NVlabs/Fast-FoundationStereo/blob/476f4249561f7c79ca707326954f9255643412a6/model_card.md)；[README](https://github.com/NVlabs/Fast-FoundationStereo/blob/476f4249561f7c79ca707326954f9255643412a6/readme.md) | **NO-GO**：只作 research/evaluation-only 资料，不进入比赛运行、打包和交付。 |
| MIT-SPARK/Kimera-VIO | `ce8c59b7b273ab5ac29db7e5572e1623760e19c7`（审计时 master 的固定快照） | [BSD 许可证](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/LICENSE.BSD)；[构建依赖](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/CMakeLists.txt)；[Triangle 条款](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/third_party/triangle/src/triangle.c) | **CONDITIONAL**：仅 cuVSLAM 阻塞时的未启用 fallback。默认构建的 Triangle 分发问题尚未关闭。 |

ROS `v5.0-0` 的 `cuvslam` gitlink 是 `33da60662b27c0c5b63e0597bd778066af2731ed`，并非独立库 `v17.0.1`。见 [固定 superproject 树](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/tree/9058506efd0b967ac894a717bdbe98df017637e5)、[.gitmodules](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/9058506efd0b967ac894a717bdbe98df017637e5/.gitmodules)、[该依赖许可证](https://github.com/nvidia-isaac/cuVSLAM/blob/33da60662b27c0c5b63e0597bd778066af2731ed/LICENSE) 及 [构建文件](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/9058506efd0b967ac894a717bdbe98df017637e5/isaac_ros_cuvslam/CMakeLists.txt)。`.gitmodules` 中的 `branch=main` 不能代替 gitlink 锁定；本次未验证替换库的 ABI/API 兼容性。

## 方法与接口审计

| 候选 | 官方输入 / 输出及接口 | 接入前必须验证的边界 |
| --- | --- | --- |
| cuVSLAM | 标定双目图像、整数纳秒时间戳；惯性模式增加 IMU 标定与按时序送入的测量。官方示例使用 `Tracker`、`register_imu_measurement`、`track`。[EuRoC 示例](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/examples/euroc/track_euroc.py) | 先 Stereo，再在时钟、外参、噪声参数核验后启用惯性模式。位姿方向、四元数顺序、坐标系和米制单位必须以实际版本接口核对，不能由方法名称推断。 |
| cuVSLAM EuRoC loader | [dataset_utils.py](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/examples/euroc/dataset_utils.py) 检查左右数量相等、配对时间戳完全相等；区分原始与 `sensor_recalibrated.yaml` 标定路径；合并 IMU 后按时间排序。 | **该 loader 的条件是时间戳完全相等**，不能把已有文档中的“相差 ≤1 ms”当成这个函数的接收条件；本次未验证底层库的最大同步容差。重配对、丢帧、标定替换须独立记录修改及输入哈希。 |
| cuVSLAM OAK-D 示例 | NVIDIA 自有的 [OAK-D README](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/examples/oak-d/README.md) 与 [run_stereo.py](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/examples/oak-d/run_stereo.py) 属 NVIDIA Community License。读取标定、CAM_B/CAM_C 双目、厘米转米、`Sync` 分组后 `track`；示例面向未校正图像。 | 官方示例验证对象是 OAK-D W Pro / DepthAI v3，不能外推全部 OAK 型号。全局快门、实际镜头模型、摄像头顺序、帧率和同步必须检查；Sync 分组门限不是硬件同步证据。 |
| ROS cuVSLAM | [节点源码](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/9058506efd0b967ac894a717bdbe98df017637e5/isaac_ros_cuvslam/src/visual_slam_node.cpp) 订阅 `visual_slam/image_i`、`camera_info_i`，VIO 模式订阅 `visual_slam/imu`；发布 `tracking/odometry`、pose、status 及路径；节点仍名 `visual_slam`。 | 重命名后不能只按旧 package 名启动；话题 remap、标定、QoS、TF 发布者和 tracking mode 需匹配。库模式与 ROS 模式不能混用未经核验的编号。 |
| EuRoC | [官方说明](https://github.com/ethz-asl/ethz-asl.github.io/blob/0ee434728bf1f13a14f86937baf53edd30ea556a/_datasets/euroc_mav.md)：双目 20 Hz、IMU 200 Hz、标定与运动参考；原数据与 NVIDIA 重标定属于不同输入配置。 | 官方列出左右自动曝光差异、动态运动下参考误差及时钟对齐局限。评估须固定序列、标定和参考来源；不把该数据当作每像素深度精度真值。 |
| DepthAI / OAK-D | [StereoDepth 头文件](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/include/depthai/pipeline/node/StereoDepth.hpp)：双目输入，深度默认毫米、视差格式随模式改变。[IMUData](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/include/depthai/pipeline/datatype/IMUData.hpp) 区分 host/device/system 时钟；[固定 IMU 示例](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/examples/python/IMU/imu_gyroscope_accelerometer.py) 使用 UNCALIBRATED 报告及批处理。 | 实际 IMU 型号、报告类型、轴向、单位、时间原点和有效速率必须实测。该 tag 的示例不能用滚动在线文档的 RAW 报告类型替代。只采用传感器/深度接口，本次不启用附带 VIO/SLAM 节点。 |
| Fast-FoundationStereo | [模型卡](https://github.com/NVlabs/Fast-FoundationStereo/blob/476f4249561f7c79ca707326954f9255643412a6/model_card.md)：校正后的双目图像 → 稠密视差；[C++ README](https://github.com/NVlabs/Fast-FoundationStereo/blob/476f4249561f7c79ca707326954f9255643412a6/cpp/README.md) 描述 TensorRT 路线。它本身不是 VO/VIO 位姿估计器。 | 仅记录方法；不运行导出、构建 TensorRT engine、取回模型或纳入飞行栈。研究权重与商业模型入口分别授权；未固定模型文件哈希。 |
| Kimera-VIO | [Pipeline.h](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/include/kimera-vio/pipeline/Pipeline.h) 提供图像/IMU 队列及 backend 输出回调；[README](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/README.md) 提供 EuRoC 与 C++ 使用入口。 | 只有 cuVSLAM 有具体阻塞才考虑适配。不能把 BSD 顶层许可扩大到内置 Triangle、词袋文件及所有依赖；不自动获取 ORB vocabulary。 |

## NVIDIA / Jetson 要求

cuVSLAM 的**许可平台条件**与**技术运行条件**分开：NVIDIA Community License §2 限定 NVIDIA GPU/CPU 系统或 NVIDIA HCA 网络系统；库的 CUDA 路径仍需要合适 GPU、驱动与运行库，满足许可证不等于可运行。[固定许可证](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/LICENSE)、[固定安装表](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/README.md)。

独立库 v17.0.1 的预编译表列出 Orin / Ubuntu 22.04 / JetPack 6.x / `cu12 cp310`，C++ Orin 资产标注 CUDA 12.6.3；Thor 对应 Ubuntu 24.04 / JetPack 7.x / `cu13 cp312-abi3`，C++ 资产标注 CUDA 13.0.1。表与文件名用于选包，不构成在本项目目标机上的验证。

ROS 的 [release-5.0 在线要求页](https://nvidia-isaac-ros.github.io/v/release-5.0/getting_started/index.html#system-requirements) 在本次访问时列出 JetPack 7.2；x86 列出 Ubuntu 24.04、Ampere+、CUDA 13.2+、driver 595+；ROS 2 Lyrical。**该版本路径下网页仍可能更新**，这是审计日观察，不是对 tag 发布当日要求的追溯；不把它与独立库 Orin/JetPack 6 配置视为同一支持组合。

DepthAI 的主机 MIT 代码没有 NVIDIA 平台条款，但设备固件限定 Luxonis 硬件。Kimera 审阅的 C++ 接口/构建没有 NVIDIA 专用依赖，README 仅声称在 Ubuntu 20.04 测过；Jetson 构建与延迟未核验。FFS 的 CUDA/TensorRT 路线只是技术描述，不能消除研究用途限制。[DepthAI 固件条款](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/notices/depthai-device-RVC2-LICENSE)、[Kimera 构建](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/CMakeLists.txt)、[FFS 模型卡](https://github.com/NVlabs/Fast-FoundationStereo/blob/476f4249561f7c79ca707326954f9255643412a6/model_card.md)。

## 证据覆盖与未执行项

[third_party.csv](../provenance/third_party.csv) 对每个已取回文件记录固定版本、URL、日期、许可证/NOTICE、SHA-256、修改状态、分发限制、平台要求和使用决定。[audit-evidence.json](../provenance/audit-evidence.json) 保存文件元数据、Git tree 完整性与 gitlink、发布资产摘要及网页访问局限；不包含第三方源码正文。

本次取回 **44 个小型源码/文档文件，共 1,244,609 字节**，只保存在 `/tmp/gps-denied-provenance-audit/`。已逐文件重算 Git blob SHA-1 与字节长度，匹配上游树后计算 SHA-256。库/模型/固件/数据集/容器均未下载或运行；14 个 cuVSLAM 发布资产只登记官方 API 摘要。历史 EuRoC/FFS 结果没有重跑，也没有在本次审计中补做历史资产授权认证。

REA **未触发**：本次问题均能从公开文档、源码、构建文件和许可证回答。将来只有针对已固定哈希的确切发布二进制、库或崩溃记录，且源码不能回答的具体问题，才评估是否需要 REA；本审计没有给出任何二进制反编译或固件分析授权。

ROS cuVSLAM gitlink `33da60662b27c0c5b63e0597bd778066af2731ed`：**CONDITIONAL**，仅作为 ROS 封装的独立依赖审计；不能以 wrapper 的 Apache-2.0 覆盖，也不视为 standalone v17.0.1 的替代。[固定依赖许可证](https://github.com/nvidia-isaac/cuVSLAM/blob/33da60662b27c0c5b63e0597bd778066af2731ed/LICENSE)。

CSV 的 `decision` 是候选比赛集成/重分发的总体决定；限定的文档/API 参考 GO 或研究评估用途不提升总体状态。内置组件继承所属候选的未放行门槛；未逐项审阅的其他依赖不视为获批。

## 一致性复核中的哈希状态

CSV 的下载状态与哈希状态分开：44 行为本地验证的小文件，14 行为官方发布但未本地验证的发布资产哈希，2 行为未固定实际资产/未核实上游哈希的占位；合计 60 行。未下载的 payload 共 16 行，包含已有官方哈希的 14 行，不能把“未下载”解释为“没有发布哈希”。

`upstream_sha256_status=NO_PUBLISHED_SHA256_IN_REVIEWED_EVIDENCE` 仅表示审阅的文件元数据中没有上游 SHA-256（44 行仍有本地计算的哈希），不声称任何地方都不存在。2 个占位使用 `NOT_ESTABLISHED`，不把未知改写成已证明没有发布哈希。原 `UNKNOWN_NOT_DOWNLOADED` 哈希占位已改为 `UNKNOWN_NOT_ESTABLISHED`，下载状态单列。

44 个来源记录对应 43 个不同内容哈希。每个本地 SHA-256 唯一绑定一个 `local_relative_path=by-sha256/<digest>` 和确切 `size_bytes`，相对根目录为 `/tmp/gps-denied-provenance-audit/`；上游来源仍由 `project`、`commit`、`artifact`、`artifact_id` 和固定 URL 区分。两个 cuVSLAM revision 的 LICENSE 字节相同，故共享同一 canonical 内容路径；不是以摘要作为唯一来源标识。缓存可能被系统清理；不在母仓库存放第三方源码。详见 [CSV](../provenance/third_party.csv) 和 [验证报告](../provenance/verification-report.json)。
