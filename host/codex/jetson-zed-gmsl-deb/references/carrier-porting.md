# 新载板与设备树适配

先建立软硬件矩阵，用 `assets/port-record.template.json` 记录未知项。未知引脚不填默认值；
可以继续不依赖该信息的源码和 ABI 准备，不把候选 DT 描述为硬件已验证。

## 必须获得的映射

每条物理 GMSL 链路记录以下完整通路，并标注证据（原理图、官方载板源、实际 DT、实测）：

`扩展板接口 → MAX96712/link → serializer/源 pipe → deserializer 目标 pipe → CSI 输出/PHY → SoC CSI brick → VI stream → virtual channel → sensor endpoint`

并记录：

- 模组型号/SKU、载板修订、SoC、端口数、扩展板型号、serializer/deserializer 型号。
- 实际 I2C 控制器节点、mux 层次、运行 bus 编号；连接器“I2C4”命名不一定等于 SoC 第四个控制器。
- camera 供电、reset、deserializer PWDN 的 GPIO、GPIO 域（MAIN/AON）与有效极性；MB1 pinmux/供电约束。
- serializer、sensor、EEPROM、IMU 物理地址、host alias 与地址转换规则；同控制分支必须唯一。
- lane 数、lane polarity、输出端口、VC、像素格式、分辨率/fps、时钟和实际带宽预算。

`tegra_sinterface`、CSI `port-index` 与 VI `port-index` 的语义不同；SoC 有共享 VI stream
时不要将 CSI brick 数字直接复制到 VI。T234 案例有 CSI E/F 共 stream4、G/H 共 stream5，
J501 第二组用 G/E 聚合及不同 VC；这不是 Thor 或其他载板的通用接法。

同总线四相机、立体每路两个 sensor、One 单 sensor，以及两块 deserializer 的混用，都需要
重新计算 serializer 源 pipe 与目标 pipe。保持源 A/B 表和分配逻辑一致，执行实际 C 回归。

## I2C 与 IMU 的已知教训

本案例旧 serializer alias `0x68/0x69` 曾碰到远端 BMI088 gyro 物理地址，驱动会误探测 gyro。
稳定 DT 将相关 serializer alias 改到 `0x6a/0x6d`；每链路 IMU 使用独立的 gyro/accel host alias。
这些数值只适用于已审查的 J501 拓扑，新扩展板必须从完整地址表重新选。

IMU 不应被整体禁用以掩盖相机问题。只有已确认的隔离实验才临时调整，并保留对照/恢复记录。
未接相机的备用 bus 上 BMI088 probe -5 不能单独证明正在使用的 bus 的 IMU 故障。
不对未知总线执行全地址扫描，不在流运行时随意改 I2C 寄存器；先使用 DT、日志与明确的只读寄存器证据。

## DT 构建与静态检查

使用目标 BSP 的 bindings、NVIDIA include 路径、carrier base DTS 和 `dtc -@`。
先用主机 gcc/cpp 预处理，再生成 overlay；不要拿其他内核的 include 文件凑合编译。
为每个支持的模块 SKU 验证：

```bash
fdtoverlay -i "$BASE_DTB" -o "$SCRATCH/merged.dtb" "$CAMERA_DTBO"
dtc -I dtb -O dts "$SCRATCH/merged.dtb" > "$SCRATCH/merged.dts"
```

核对互相指向的 remote-endpoint、实际 enabled 状态、同 I2C 分支 alias 唯一、IMU 引用、
VI/CSI/VC 路由、sensor `reg`/`devname`/`proc-device-tree` 一致及 mode 的 lane/clock。
多个相机型号的候选节点可以共存，不能把 24 个候选节点描述为实际 24 台相机。

Argus 模块 badge 与 tuning 必须匹配；本案例双目左右 badge 均为 `zedx_ar0234`，但
drivernode/proc-device-tree 不同。JP6 使用参考 `position=front` 规避曾见的不支持位置字符串，
不要为了唯一性发明 Argus 不接受的 position。新 SDK/型号仍需实测 badge/命名规则。

J501 旧注释提到 serial_a/b polarity 6，而稳定传参实际为 0；迁移时以源、原理图和
对应接线下的成功抓帧为依据，不能根据单条陈旧注释盲改。

## 载板打包与引导

新建对应载板的 overlay/config 和包名，避免拿 Mini 的 GPIO 配 Robo。
旧 `package.sh` 可能只识别 `zedx-j501-mini/robo`：检查 `carrier`、DTB glob、互斥依赖、
depmod 模块路径及 extlinux 选择函数，给新板补充明确分支；仅改 `-n` 参数不算适配完成。

基础 DTB 选择优先级应基于实际默认启动项、当前载板和模块 SKU，不能取 `/boot/*.dtb` 的第一个。
处理 `/boot` 与 `/boot/dtb` 同内容副本：按内容/SKU 判断，不能仅以候选文件数报“无法唯一选择”。
需使用附带 base DTB 时，记录其源码和全部依赖，并确认它与目标 BSP/其他外设兼容。

用原 ZED extlinux 工具添加独立启动项，保留根分区参数和其他无关 overlay；替换历史冲突的相机 overlay。
先做真实 `fdtoverlay` 合并，再临时写入、fsync、原子替换配置；保留可用备份。
测试重复安装无重复 LABEL、SKU 回退正确和 upgrade 不误恢复旧启动项。
