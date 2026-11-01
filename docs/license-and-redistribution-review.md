# 许可证与重分发审计

审计日期：2026-10-31（America/Los_Angeles），证据取回日期 2026-11-01 UTC。版本和总体结论以 [方法矩阵](upstream-method-matrix.md) 为准。本次未修改任何上游文件，也未将第三方源码复制到母仓库。临时文件的读取许可、运行许可和对外重分发许可分别判断。

## cuVSLAM：CONDITIONAL

固定 `v17.0.1` / `51631ba358ea51262342f9ae649820d639363eb9`；[NVIDIA Community License](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/LICENSE)（文本版本 February 25, 2026），SHA-256 `f369a8d255622b2ad0108b65dacb62b96c40a3a113f7893218436188bdc373fd`。

该许可允许商业使用与衍生作品，但 §2 将使用、复制、修改和分发许可限定于 NVIDIA Platforms：含 NVIDIA GPU 或 CPU 的系统，或用于 NVIDIA HCA 系统联网的情形。不能把它概括为普通无平台限制的开源许可。只调用接口或独立安装并不会使库自身脱离这个约束。

§3 要求向接收方提供许可证，分发源码衍生物时保留相关版权、专利、商标和归属声明；如果发行物包含 NOTICE，分发衍生物时按该条保留归属并附 `Licensed by NVIDIA Corporation under the NVIDIA Community License.`。固定 Git 树只找到 `LICENSE` 与 `license_header.txt`，没有独立 NOTICE；**尚未查看 wheel/C++ archive 内部**，因此这不是对发布包不存在 NOTICE 的结论。许可的商标、责任承担和贸易合规条款仍适用。[固定树](https://github.com/nvidia-isaac/cuVSLAM/tree/51631ba358ea51262342f9ae649820d639363eb9)。

决定：只保留外部依赖与文档接口路线；必须确认实际 NVIDIA 目标机、确切包、包内许可证/NOTICE 及 CUDA 等运行依赖，才能批准安装/分发方案。README 的性能和兼容说明不是本项目测试结果。[固定 README](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/README.md)。

## Isaac ROS cuVSLAM：CONDITIONAL

固定 `v5.0-0` / `9058506efd0b967ac894a717bdbe98df017637e5`。wrapper 的 [LICENSE](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/9058506efd0b967ac894a717bdbe98df017637e5/LICENSE) 是 Apache-2.0，SHA-256 `58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd`；包已重命名为 `isaac_ros_cuvslam`。[固定 README](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/9058506efd0b967ac894a717bdbe98df017637e5/README.md)。

分发 wrapper 时附 Apache-2.0、保留相关归属；若修改并分发文件，须显著标明修改；若上游提供 NOTICE，保留相应归属。wrapper 完整 Git 树未发现独立 NOTICE。Apache-2.0 不覆盖 `cuvslam` gitlink；后者固定 `33da60662b27c0c5b63e0597bd778066af2731ed`，其 [LICENSE](https://github.com/nvidia-isaac/cuVSLAM/blob/33da60662b27c0c5b63e0597bd778066af2731ed/LICENSE) 也是 NVIDIA Community License，独立记录哈希 `f369a8d255622b2ad0108b65dacb62b96c40a3a113f7893218436188bdc373fd`。对该依赖仅取回 LICENSE，未声称完成其全树或所有依赖审查。

决定：ROS 接口可继续审阅；wrapper、库、CUDA 及 ROS 其他依赖须分别列入实际分发包清单。没有批准以 Apache-2.0 给整个组合重新授权，也没有验证将 gitlink 换成独立库 v17.0.1。[.gitmodules](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/9058506efd0b967ac894a717bdbe98df017637e5/.gitmodules)、[构建关系](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/9058506efd0b967ac894a717bdbe98df017637e5/isaac_ros_cuvslam/CMakeLists.txt)。

## EuRoC MAV：CONDITIONAL

数据固定标识为 [DOI 10.3929/ethz-b-000690084](https://doi.org/10.3929/ethz-b-000690084)，ETH 记录日期 `2024-09-27`；官方说明源码固定 `0ee434728bf1f13a14f86937baf53edd30ea556a`，该说明文件 SHA-256 `a51da9c1ab058ca5f85b0260941dfa1d39d5fd65597aa185af927d79be9bf344`。[固定说明页源码](https://github.com/ethz-asl/ethz-asl.github.io/blob/0ee434728bf1f13a14f86937baf53edd30ea556a/_datasets/euroc_mav.md)。

[ETH 官方记录](https://www.research-collection.ethz.ch/items/bcaf173e-5dac-484b-bc37-faf97a594f1f) 的搜索索引在本次访问显示 Rights / License 为 **In Copyright - Non-Commercial Use Permitted**。直接读取记录页返回 HTTP 403，故这是官方域名索引证据，尚未取得原始页面或各压缩包内条款。该 [权利声明原文](https://rightsstatements.org/page/InC-NC/1.0/?language=en) 允许非商业用途，其他用途需权利人许可，且明确自身不是许可证；不能把它写成 CC-BY、BSD 或“公开下载即无限制”。

数据归属、论文署名与非商业使用范围须保留。引用 Burri 等人的 IJRR 2016 论文，论文 DOI `10.1177/0278364915620033`，由 [官方说明](https://github.com/ethz-asl/ethz-asl.github.io/blob/0ee434728bf1f13a14f86937baf53edd30ea556a/_datasets/euroc_mav.md) 指定。Kimera 测试目录里的 [MicroEurocDataset/LICENSE.md](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/tests/data/MicroEurocDataset/LICENSE.md) 只有归属指针，不能替代 ETH 的授权，也不能继承 Kimera 的 BSD 许可。

决定：明确非商业的内部研究评估可按权利声明继续准备；比赛展示、公开示例帧/视频、数据再分发及商业用途均未获本审计放行。需确认比赛使用性质及确切数据包条款。实际 dataset 没有 Git commit/tag；DOI 是记录标识，不能代替每个 ZIP/序列的内容 SHA-256。本次未下载数据，CSV 显式写 `UNKNOWN_NOT_ESTABLISHED`；说明页哈希不当作数据哈希。官方说明从旧下载页迁移到 ETH Research Collection，后续按 DOI 核对，不采用第三方镜像作为授权来源。

## DepthAI 主机库与官方 OAK-D 示例：CONDITIONAL

固定 `v3.11.0` / `e9ead6536e1bf9842d91211fcf80f0b4ef119954`；顶层 [LICENSE](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/LICENSE) 为 MIT，SHA-256 `5fe6d4ec2aa4e228142ee71084d1c8bfea474238fee8d49bd10e8cbd0b44ace1`。同一版本的 [StereoDepth 示例](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/examples/python/StereoDepth/stereo.py) 与 [IMU 示例](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/examples/python/IMU/imu_gyroscope_accelerometer.py) 供接口参考；本次不复制。MIT 主机代码允许使用、修改、商业使用和分发，复制或实质部分分发须保留版权及许可声明。

发行包另有独立条款，不能仅提交 MIT 文本：

| 范围 | 官方固定证据 | 本次审计结果 |
| --- | --- | --- |
| 主机第三方组件 | [THIRD_PARTY_NOTICES](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/notices/THIRD_PARTY_NOTICES) | 文件列出具体构建选项、依赖版权和许可证，含 MPL/LGPL 等文本；存在文本不证明目标包实际链接了全部组件，也不自动代表全部已满足义务。 |
| RVC2 固件 | [depthai-device-RVC2-LICENSE](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/notices/depthai-device-RVC2-LICENSE) | Luxonis Firmware Package License 限定仅在 Luxonis 硬件运行，分发保留许可/版权，附带组件另有条款。 |
| RVC4 固件 | [depthai-device-RVC4-LICENSE](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/notices/depthai-device-RVC4-LICENSE) | 同样限定 Luxonis 硬件；另列 ST VD55H1 IPP/SLA0106 的传感器使用及分析/竞争产品限制，以及出口和分发条款传递要求。不能以主机 MIT 覆盖。 |
| 可选可视化/动态标定 | [notices 目录](https://github.com/luxonis/depthai-core/blob/e9ead6536e1bf9842d91211fcf80f0b4ef119954/notices) | 树中还存在 `depthai-visualizer-LICENSE`、`dynamic_calibration-LICENSE`；本次只登记路径，未逐条审阅，不批准打包这些组件。 |

决定：主机 API/普通双目与 IMU 示例的文档参考为 **GO**；整个 OAK 部署与重分发仍 **CONDITIONAL**。冻结目标设备及 RVC 代际、实际 wheel/native 库与固件版本/hash、启用构建选项和随包 NOTICE 后，才能决定对应的源代码提供、许可附带或其他义务。本次没有下载固件或批准对其使用 REA。

另外，NVIDIA 仓库的 [OAK-D run_stereo.py](https://github.com/nvidia-isaac/cuVSLAM/blob/51631ba358ea51262342f9ae649820d639363eb9/examples/oak-d/run_stereo.py) 属 NVIDIA Community License，**不是** Luxonis MIT 示例；按文件来源适用许可。

## Fast-FoundationStereo：NO-GO（比赛交付）

固定 `476f4249561f7c79ca707326954f9255643412a6`；[LICENSE.txt](https://github.com/NVlabs/Fast-FoundationStereo/blob/476f4249561f7c79ca707326954f9255643412a6/LICENSE.txt) SHA-256 `045b564ebafefaa863beec07c5acdcfa8d99cefbbd060c22865bc4613318ddd6`。§3.3 将非商业用途进一步定义为研究目的，并延及衍生作品；§3.1/3.2 规定随附完整许可、保留通知及延续用途限制。因此目前只作 **research/evaluation-only**，不把比赛获奖、展示或交付自行认定为研究许可范围。

[模型卡](https://github.com/NVlabs/Fast-FoundationStereo/blob/476f4249561f7c79ca707326954f9255643412a6/model_card.md) 写明研究/评估用途，但许可链接指向另一个 FoundationStereo 仓库；该交叉链接不能替代本次固定 LICENSE.txt 或证明权重授权。固定 [README](https://github.com/NVlabs/Fast-FoundationStereo/blob/476f4249561f7c79ca707326954f9255643412a6/readme.md) 已分别列研究 checkpoint 和商业 `C-Fast-FoundationStereo` / NVIDIA Open Model Agreement / TAO 入口；这说明授权对象有区别，不能用商业 checkpoint 的许可覆盖本仓库推理代码。没有下载权重，也没有核实其版本、模型卡、许可证和 SHA-256；不新增模型候选或 TAO 集成。

固定 Git 树未发现独立 NOTICE；仍应保留源码中版权和归属。母仓库已有离线脚本 `benchmarks/gps_denied/run_ffs_euroc.py`，其自行声明研究用途；本次未运行、重写或认证其源码来源。该脚本、FFS 依赖、checkpoint、派生 ONNX/TensorRT engine 及已有 FFS 示例媒体均不能仅凭本审计进入比赛发行包。历史研究指标可保留为内部研究记录，若要公开使用须另行关闭授权及输入数据问题。

## Kimera-VIO：CONDITIONAL，fallback 未启用

固定 `ce8c59b7b273ab5ac29db7e5572e1623760e19c7`；[LICENSE.BSD](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/LICENSE.BSD) 的两条条件对应 BSD-2-Clause，SHA-256 `9cf61e2c9ebb83fe29e3981ae79540fd7a82d2aefc3ce5f7242e2131e40e7d70`。源码分发保留版权、条件和免责声明；二进制分发在文档或其他随附材料复现。嵌入的 [ANMS LICENSE](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/src/frontend/feature-detector/anms/LICENSE) 是 MIT，也需单独保留。

**默认构建有额外分发阻塞。** [主 CMake](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/CMakeLists.txt) 无条件加入 `third_party` 并链接 `triangle::triangle`；[third_party/CMakeLists.txt](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/third_party/CMakeLists.txt) 加入 Triangle。[triangle.c 文件头](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/third_party/triangle/src/triangle.c) 规定免费分发与保留通知，修改版本另有源/目标代码免费提供和修改声明要求；作为商业系统分发需与作者直接安排。不能将主库 BSD 许可套用于此组件，也不能假定关闭运行时 mesher 就消除链接依赖。本次读取文件及构建关系，没有替换、删除或重写实现。

此外 [构建文件](https://github.com/MIT-SPARK/Kimera-VIO/blob/ce8c59b7b273ab5ac29db7e5572e1623760e19c7/CMakeLists.txt) 在词袋缺失时会尝试下载 ORB vocabulary；该资产的实际版本、哈希及授权未核清，不执行 configure/build。GTSAM、OpenGV、DBoW2、Kimera-RPGO 等仅识别依赖名称，未完成版本及许可证审计；ROS wrapper 不在本次启用范围。

决定：保留为 cuVSLAM 有明确阻塞时的唯一 fallback；激活前先关闭 Triangle/词袋及必要依赖授权、构建和目标机接口问题。默认组合二进制的比赛分发当前不放行；没有启动多框架排行榜或新 benchmark。

## 哈希、修改与重分发记录的解释

- `third_party.csv` 的源码/文档 SHA-256 为实际取回 UTF-8 文件字节；逐一匹配上游 Git blob SHA-1 与长度，未把 Git commit/SHA-1 冒充 SHA-256。
- cuVSLAM 发布资产 SHA-256 来自 [官方 release API](https://api.github.com/repos/nvidia-isaac/cuVSLAM/releases/tags/v17.0.1) 的 `digest`；标为 `UPSTREAM_REPORTED_NOT_LOCALLY_VERIFIED`，没有声称下载或独立验证。
- 数据集、模型、实际固件和发布包内部 NOTICE 未取回；未知项明确保留，不拿源码 LICENSE 或说明页哈希代替。
- “未修改”仅指本次审计没有改上游；不代表已认证历史 checkout、既有适配器、既有研究结果或示例媒体的来源/许可。全树 NOTICE 搜索不递归展开 gitlink，边界记录在 [audit-evidence.json](../provenance/audit-evidence.json)。

本次没有准备第三方二进制分发物，因此本文件是审计与门槛记录，并非已经随包完成的 LICENSE/NOTICE 汇编。后续发行负责人须对实际包逐项关闭门槛，不能仅把本报告当作所需许可正文。

ROS cuVSLAM gitlink `33da60662b27c0c5b63e0597bd778066af2731ed`：**CONDITIONAL**，仅作为 ROS 封装的独立依赖审计；不能以 wrapper 的 Apache-2.0 覆盖，也不视为 standalone v17.0.1 的替代。[固定依赖许可证](https://github.com/nvidia-isaac/cuVSLAM/blob/33da60662b27c0c5b63e0597bd778066af2731ed/LICENSE)。

CSV 的 `decision` 是候选比赛集成/重分发的总体决定；限定的文档/API 参考 GO 或研究评估用途不提升总体状态。内置组件继承所属候选的未放行门槛；未逐项审阅的其他依赖不视为获批。

## 一致性复核中的哈希状态

CSV 的下载状态与哈希状态分开：44 行为本地验证的小文件，14 行为官方发布但未本地验证的发布资产哈希，2 行为未固定实际资产/未核实上游哈希的占位；合计 60 行。未下载的 payload 共 16 行，包含已有官方哈希的 14 行，不能把“未下载”解释为“没有发布哈希”。

`upstream_sha256_status=NO_PUBLISHED_SHA256_IN_REVIEWED_EVIDENCE` 仅表示审阅的文件元数据中没有上游 SHA-256（44 行仍有本地计算的哈希），不声称任何地方都不存在。2 个占位使用 `NOT_ESTABLISHED`，不把未知改写成已证明没有发布哈希。原 `UNKNOWN_NOT_DOWNLOADED` 哈希占位已改为 `UNKNOWN_NOT_ESTABLISHED`，下载状态单列。

44 个来源记录对应 43 个不同内容哈希。每个本地 SHA-256 唯一绑定一个 `local_relative_path=by-sha256/<digest>` 和确切 `size_bytes`，相对根目录为 `/tmp/gps-denied-provenance-audit/`；上游来源仍由 `project`、`commit`、`artifact`、`artifact_id` 和固定 URL 区分。两个 cuVSLAM revision 的 LICENSE 字节相同，故共享同一 canonical 内容路径；不是以摘要作为唯一来源标识。缓存可能被系统清理；不在母仓库存放第三方源码。详见 [CSV](../provenance/third_party.csv) 和 [验证报告](../provenance/verification-report.json)。
