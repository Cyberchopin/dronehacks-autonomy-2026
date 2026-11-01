# GPS-denied 上游集成决策

日期：2026-10-31（America/Los_Angeles）。本决策只处理证据、许可及后续接入边界；没有更改运行代码、安装依赖或批准飞行使用。源码固定版本和官方链接见 [方法矩阵](upstream-method-matrix.md)，每个证据文件与哈希见 [CSV](../provenance/third_party.csv)。

## 使用决定

| 候选 | 决定 | 当前允许的动作 | 交付前条件 |
| --- | --- | --- | --- |
| cuVSLAM v17.0.1 | **CONDITIONAL**，主候选 | 继续公开接口与本地依赖方案审阅 | NVIDIA 平台、匹配包和运行环境、包内许可/NOTICE、实际文件哈希与接口验证。[许可证](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/LICENSE) |
| Isaac ROS cuVSLAM v5.0-0 | **CONDITIONAL**，可选封装 | 审阅 `isaac_ros_cuvslam` 接口 | 独立核对 gitlink 和 ROS/JetPack 支持；不能自动替换为 standalone wheel。[构建文件](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/9058506efd0b967ac894a717bdbe98df017637e5/isaac_ros_cuvslam/CMakeLists.txt) |
| EuRoC MAV | **CONDITIONAL**，离线评估输入 | 准备非商业研究协议、输入清单 | 权利范围、序列/压缩包版本与哈希；公开媒体/数据单独审查。[ETH 权利记录](https://www.research-collection.ethz.ch/items/bcaf173e-5dac-484b-bc37-faf97a594f1f) |
| DepthAI / OAK-D 官方示例 | **CONDITIONAL**，传感器与深度路径 | MIT API/示例参考 **GO** | 实际 OAK 型号、RVC 固件与发布包、对应 NOTICE/依赖、时钟与标定验证。[主机许可](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/LICENSE)、[固件条款](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/notices/depthai-device-RVC2-LICENSE) |
| Fast-FoundationStereo | **NO-GO**，比赛交付 | 仅保留 research/evaluation-only 方法及许可记录 | 必须有覆盖实际代码、权重及比赛用途的明确授权，另开审查后才能改判。[研究限制](https://github.com/NVlabs/Fast-FoundationStereo/blob/476f4249561f7c79ca707326954f9255643412a6/LICENSE.txt) |
| Kimera-VIO | **CONDITIONAL**，fallback 未启用 | 仅保留本次审计 | 先记录 cuVSLAM 阻塞，再关闭 Triangle、词袋与依赖许可及目标机接口。[Triangle 条款](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/third_party/triangle/src/triangle.c) |

项目总体路线：**OAK-D 传感器输入 → 外部安装的 cuVSLAM Stereo → 项目自己的定位证据/监督接口**。惯性模式待时钟与外参证据满足后再评估；ROS 只是可选接口层。这是选择记录，尚未实施或通过硬件验收。NVIDIA 官方 [OAK-D 示例](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/examples/oak-d/README.md) 支持该输入路线，但不证明本项目设备可直接使用。

## 阻塞清单与关闭证据

| ID | 门槛 | 所需可审阅证据 | 负责环节 / 当前状态 |
| --- | --- | --- | --- |
| CUV-01 | NVIDIA Community License 平台要求 | 目标系统型号、GPU/CPU、Ubuntu、JetPack/CUDA/driver；确认所有实际运行目标符合 §2 | 集成负责人；OPEN。[许可](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/LICENSE) |
| CUV-02 | 确切发布包及随包通知 | 选择一个平台对应资产；受控获取时比对官方 SHA-256，再盘点包内 LICENSE/NOTICE 及运行依赖；不能只验证 Git tag | 发行负责人；OPEN。[v17.0.1 发布资产](https://github.com/nvidia-isaac/cuVSLAM/releases/tag/v17.0.1) |
| CUV-03 | 输入/输出接口一致性 | 实际 OAK 标定、全局快门、左右帧配对、设备时钟、外参/单位/坐标系；失效与重定位行为的验收记录 | 硬件/接口负责人；OPEN。[官方示例](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/examples/oak-d/run_stereo.py) |
| ROS-01 | wrapper/库及系统版本 | 保持固定 gitlink；记录版本化 OS/ROS/JetPack 要求，必要时另审匹配旧版本；不得默认混装 v5.0-0 + v17.0.1 | ROS 接口负责人；OPEN。[源码](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/tree/9058506efd0b967ac894a717bdbe98df017637e5)、[审计日在线要求](https://nvidia-isaac-ros.github.io/v/release-5.0/getting_started/index.html#system-requirements) |
| EUR-01 | 数据授权与字节身份 | 直接可访问的 ETH 权利/包内条款记录、用途范围判断、具体序列与实际文件 SHA-256；比赛展示媒体另列 | 评估/发行负责人；OPEN，官方记录直接访问 403。[ETH](https://www.research-collection.ethz.ch/items/bcaf173e-5dac-484b-bc37-faf97a594f1f) |
| OAK-01 | 主机与固件许可分层 | RVC 代际、确切 SDK/firmware version/hash、实际启用组件、对应完整 NOTICE/许可、分发义务表 | 设备/发行负责人；OPEN。[NOTICE](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/notices/THIRD_PARTY_NOTICES) |
| FFS-01 | 研究限制与模型授权 | 覆盖具体代码和权重版本、比赛用途、派生 engine 与再分发的许可；仅有商业 checkpoint 链接不关闭本项 | 发行负责人；BLOCKED_FOR_COMPETITION，维持 NO-GO。[LICENSE](https://github.com/NVlabs/Fast-FoundationStereo/blob/476f4249561f7c79ca707326954f9255643412a6/LICENSE.txt)、[README](https://github.com/NVlabs/Fast-FoundationStereo/blob/476f4249561f7c79ca707326954f9255643412a6/readme.md) |
| KIM-01 | fallback 触发 | 记录 CUV-01/02/03 或可复现运行阻塞、影响和尝试；只决定是否激活 Kimera，不新增其他框架 | 集成负责人；NOT_TRIGGERED |
| KIM-02 | fallback 组合依赖分发 | Triangle 具体许可安排及符合用途的分发方案；ORB vocabulary 来源/哈希/授权；必要依赖版本及通知清单 | fallback/发行负责人；OPEN。[默认构建](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/CMakeLists.txt)、[Triangle](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/third_party/triangle/src/triangle.c) |

以上是后续工作清单，本次没有执行下载、安装、固件分析或适配实现。没有证据证明 cuVSLAM 已发生阻塞，因此 **Kimera fallback 不启动**。

## 母仓库与比赛发布范围

本次允许进入仓库的变更仅为这组审计文档、CSV 和派生元数据。第三方源码正文只暂存 `/tmp`；不新增 submodule、vendor 目录、模型、数据、容器或第三方许可证正文副本。若以后分发第三方包，仍须随实际包提供其要求的完整许可/通知，本审计的链接不能代替该义务。

现有 `run_cuvslam_euroc.py` 按文档从外部 checkout 导入上游 loader；现有 `run_ffs_euroc.py` 从外部源码目录载入模型。这只能说明当前接口方式，不能证明既有适配代码是否构成衍生作品，也不构成历史资产来源认证。本次没有更改或重写这些文件。FFS 运行脚本、依赖、checkpoint、ONNX/TensorRT engine 与既有 FFS 媒体按 FFS-01 从比赛包中排除；EuRoC 帧/视频受 EUR-01 约束。此处是**发布策略记录**，尚未修改任何打包脚本或审计实际发布包。

不新增性能排行榜，不复述已有研究数字为本次验证结果，不把官方 README 的结果当作目标 Jetson 测量。源码或文档能回答的问题继续用源码/文档/接口审计；只有明确、固定哈希的二进制/库/崩溃问题且源码不足时才考虑 REA，并先核对对应条款。

ROS cuVSLAM gitlink `33da60662b27c0c5b63e0597bd778066af2731ed`：**CONDITIONAL**，仅作为 ROS 封装的独立依赖审计；不能以 wrapper 的 Apache-2.0 覆盖，也不视为 standalone v17.0.1 的替代。[固定依赖许可证](https://github.com/nvidia-isaac/cuVSLAM/blob/33da60662b27c0c5b63e0597bd778066af2731ed/LICENSE)。

CSV 的 `decision` 是候选比赛集成/重分发的总体决定；限定的文档/API 参考 GO 或研究评估用途不提升总体状态。内置组件继承所属候选的未放行门槛；未逐项审阅的其他依赖不视为获批。
