# J501 固定基线与证据

这份记录保留本项目已完成工作的边界。提交号是历史固定输入，不代表当前远端最新。
本技能不包含现场密码或固定 SSH 目标，不自动连接历史设备。

## 软件矩阵与已完成验证

| 环境 | 发布包 | 模块 | 实机证据 |
| --- | --- | --- | --- |
| JP7.2 / R39.2.0 / 6.8.12-1021-tegra | 1.4.4.4-L4T39.2.0 | 10 个配套模块 | Mini 用户反馈当前最稳定，连续时长未记录；Robo 后续同包重启恢复，见下文 |
| JP6.2.1 / R36.4.4 / 5.15.148-tegra | 1.4.4.4+seeed1-L4T36.4.4 | 5 个 ZED/IMU 模块 | Robo 六路 video、四机 SDK 并发各 300 帧通过；Mini 载板仅离线 |

J501 Mini 是载板名称，ZED X Mini 是相机型号。Robo 上测过 ZED X Mini **不代表 Mini 载板已测试**。
JP6 单机图像测试为 HD1200@30、1920×1200、300/300 帧；四机组合为两台 One GS
HD1200@15、两台双目 HD1200@30，各 300/300 帧，深度 NONE，IMU 保留。
尚无 JP6 Studio GUI、长时间、反复重开及冷启动验收记录。

离线历史结果：JP7.2 每包 33 个依赖模块/2774 项 CRC；修正版 JP6 每包
25 个依赖模块/1518 项 CRC，其中五个新模块 200 项导入 CRC。
数量来自固定版本，其他 BSP 不要求凑成同样数字。

## 源码来源

- 摄像头/SerDes/BMI088：Seeed-Studio/Linux_for_Tegra `r39.2.0`，
  `c018d61c5feb7951a16317b03ec9e0be6d6cb8cb`。
- daemon、Debian rules、extlinux 的 ZED 工程基线：`70277995566b8b2a1f7fba9d6518d7ab893b462b`。
- JP6 Seeed `camera_common.h`：Seeed `r36.4.4` 的固定提交
  `def3d7ff8fbb34cea0b6b43c89a7aae1872651ef`。实机镜像记录的提交是
  `90b4a5bce6d910095473e1631c4a31de58b6949d`，两者不可混写。
- JP6 的 14 个核心 ZED/SerDes/BMI088 C/头文件与保存的 JP7.2 稳定快照哈希一致。
  这不包括 Seeed/NVIDIA 接口头文件、Makefile、DT 和维护脚本。

可复查的历史网址：

- https://github.com/Seeed-Studio/Linux_for_Tegra/tree/c018d61c5feb7951a16317b03ec9e0be6d6cb8cb
- https://github.com/Seeed-Studio/Linux_for_Tegra/blob/def3d7ff8fbb34cea0b6b43c89a7aae1872651ef/source/nvidia-oot/include/media/camera_common.h

## 1.4.4.4 真正新增的修复

`sl_max96712_pipes_setup()` 旧版每遇到一台同 I2C 总线的已发现相机都左移两位。
同总线上第三、第四台相机的 serializer 源掩码变成 `0x10/0xc0`，超出 X/Y/Z/U
有效范围。探测和 video 枚举仍可成功，不能以 `camera pipeline operational` 当作已分配图像通路。

稳定版按同总线前序相机数奇偶交替选择源 X/Y、Z/U，使 serializer A/B 配置表和
MAX96712 输入映射一致。不同 serializer 可重复使用同名源 pipe，目标 deserializer pipe 仍独立。
两台 One+两台双目的例子为 `0x01,0x0c,0x01,0x0c`，六条目标 pipe 对应 `0x3f`；
`0x3f` 不是任何相机组合的通用常量。实际 C 回归涵盖六种排列，包括四双目八条 pipe。

补丁原件随技能保存于 `assets/0001-j501-four-camera-pipe-allocation.patch`。
在固定的未修正基线上先 `git apply --check`，确认路径/逻辑匹配后再应用；稳定源已包含该修改，不能重复应用。

已继承的 daemon 修正是：忽略非采集端口 FROZEN，采集中持续 FROZEN 5 秒后再考虑恢复，
保留 60 秒全局恢复间隔。该修正处理恢复抖动，不替代视频 pipe 修复。

## JP6 初版的失败与更正

初版 `1.4.4.4-L4T36.4.4` 已被 `+seeed1` 替代。官方 headers 与实际 Seeed 核心
不匹配，使 `sl_zedx` 八项符号 CRC 错误。官方版本在实机 `/usr/src` 中仍存在，不能直接信任。
Seeed 的 `tegracam_ctrl_ops` 新增 `set_trig_mode`，从 168 变为 176 字节，成员偏移 168。
目标 ko 的 DWARF 与编译探针对比：官方头文件 8/9 结构体匹配，Seeed 头文件 9/9 匹配。
修复同时更新头文件与来自实际 camera ko 的符号表，没有使用 force load。

旧离线脚本还漏合并官方包的 `/lib/modules` 与 `/usr/lib/modules`，只校验了不完整依赖。
新检查必须检查各模块 `depends`，不能仅看 depmod/modprobe 命令成功。

## JP7.2 Robo 的运行状态故障

2026-11-05 后续排查中，Robo 相机已枚举、四条物理 link 与 IMU 正常，但 Argus
GpuBlitStage 线程阻塞于 GPU channel close，伴随 DCE RPC 超时。
授权重启后，同一个未修改的 1.4.4.4 包恢复推流，Studio 运行，六路 video link/video lock 为 1。
不能将这次恢复写成新的 deb 补丁生效，也未隔离首次触发故障的条件。
归档中较早的“Robo 仅离线”标记反映当时状态，后续诊断记录补充了上述实机恢复证据。

## 本机原始记录位置（可选，不是技能运行依赖）

- JP7.2：`/other_data/39.2.0/zedx-driver-bsp-j501/release/j501-jp72-1.4.4.4-complete/`
  中的 `CHANGES_1.4.4.4_VS_CN.md`、`REBUILD_CN.md`、`records/`、`debs/`。
  当前 checkout 缺失原始 `dependencies/`，不能声称已经包含所有重编译依赖。
- JP7.2 后续 Robo 诊断：同工作区 `release/diagnosis-1.4.4.4-robo-20261105/DIAGNOSIS_CN.md`。
- JP6：`/other_data/36.4.3-nvidia-devkit/zedx-driver-bsp/release/j501-jp621-package-sh-1.4.4.4+seeed1/`
  的 `README.md`、`BUILD_MANIFEST.json`、`VERIFICATION.json`、`HARDWARE_VERIFICATION.json` 和 `hardware-logs/`。
- JP6 编译依赖包含原 `r3644-build-support.tar.gz` 和修正后的 `seeed1-build-support.tar.gz`；
  源码包中没有完整编译器。该旧目录名里的 36.4.3 不代表产物实际 L4T。

稳定版摄像头源码在保存快照的 `seeed-upstream-r39.2.0/source/nvidia-oot`。
原工作区 `src/kernel` 中有旧试验文件，不应看到同名文件就当作当前发布源码。
