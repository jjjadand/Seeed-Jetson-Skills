---
name: jetson-zed-gmsl-deb
description: >-
  为 Jetson 自定义载板适配、构建或排查 Stereolabs ZED GMSL 的 deb 驱动，
  沿用 ZED package.sh/Debian rules。包含 JetPack 7.2/R39.2.0 和
  JetPack 6.2.1/R36.4.4 的可复现案例、实机 ABI 校验、DT/IMU 路由、
  NITO/ISP 区分及 SDK 收帧验收。适用于迁移到其他载板，不用于普通 USB ZED 安装。
---

# Jetson ZED GMSL deb 适配

以保存的构建输入、实际 deb 和目标机日志建立可复现链条。基于 2026-11-05
完成的 J501 Mini/Robo 案例整理，技能整理日期为 2026-11-11。
案例记录的版本与提交是固定基线；用户要求“最新”时重新核对指定远端并固定提交。

## 先确定工作模式

- **重现旧包**：先读 [J501 基线与证据](references/j501-baselines.md)，再读对应版本的构建方法。复用的二进制必须记录来源与 SHA256，不能称为全部重新编译。
- **为新载板适配**：先读 [载板与设备树](references/carrier-porting.md)，用 [适配记录模板](assets/port-record.template.json)记录软硬件矩阵，再进入对应版本构建。
- **枚举、开流或安装故障**：先读 [验证与排障](references/validation-and-troubleshooting.md)，按首发错误所处阶段检查。仅诊断的任务不自动安装或重启。

版本构建参考：

| 已验证的案例环境 | 必读参考 | 主要区别 |
| --- | --- | --- |
| JP7.2 / R39.2.0 / 6.8.12-1021-tegra | [JP7.2 构建](references/build-jp72.md) | NITO；本案例为 10 个配套模块 |
| JP6.2.1 / R36.4.4 / 5.15.148-tegra | [JP6 构建](references/build-jp6.md) | 文本 ISP；本案例为 5 个 ZED/IMU 模块，保留 Seeed camera 核心 |

不要用 JetPack 营销版本或目录名推断 L4T 和内核；其他 JP6.2 小版本需要实测其精确 ABI。

## 工作约束

1. 沿用用户指定的 **ZED 工作目录 `package.sh → repack/debian/rules → dpkg-buildpackage`**。
   可以让原脚本接收明确的已编译输出；本技能不提供自制 deb 生成器。
2. 保存原工作区改动与稳定包，再用独立构建目录迭代。区分 Seeed/NVIDIA 内核源、ZED daemon/打包源和本地补丁，分别固定提交。
3. 与**实际选中的目标 camera 核心模块**比较导出 CRC。即便 `/usr/src` 和官方 `Module.symvers` 标为相同 L4T，也可能不是运行模块的接口。
   发现类型变化时使用匹配的头文件重编译，并核对结构体布局/对应源码；仅改 CRC 或强制加载不能证明 ABI 兼容。
4. 每块载板单独核对 GPIO、I2C、serializer/IMU 别名、CSI、VI、VC 和模块 SKU。J501 地址和路由仅作案例。
   IMU 是验收的一部分；要解释无 IMU 的短期隔离测试与最终功能验证的区别。
5. 区分编译通过、离线包检查、实机枚举、SDK 收帧、Studio GUI 和长期稳定性。
   前一级通过不能替代后一级；报告准确的相机组合、帧数、速率、时长及是否保留 IMU。
6. 构建和离线检查本身不授权安装、停止其他相机应用、重启服务或整机。
   先使用会话已有授权；部署被授权后按 [验证参考](references/validation-and-troubleshooting.md)执行并记录恢复状态。

## 执行顺序

### 1. 建立版本与来源记录

读取 `uname -r`、`/etc/nv_tegra_release`、BSP 镜像提交、实际 boot FDT/overlay、
`modinfo -n tegra_camera`、服务状态和已安装包。可在已获访问权限的目标机上运行：

```bash
bash scripts/collect_target.sh --output ./target-evidence
```

脚本只收集本机证据；不会 SSH、扫描 I2C 地址、加载模块或重启。目录可能包含设备标识，分享前检查。
没有目标机时可继续编译候选包，但将目标 ABI/实机验证标为未确认。

### 2. 准备 ABI、构建与调参输入

按对应版本参考准备精确内核生成头文件、配置、符号表、OOT/conftest、编译器/sysroot、
实际核心模块和匹配的 camera 头文件。读取相关版本参考后再选择模块集；不要直接套用固定的 5/10 数字。

分开编译模块、DT、daemon，清楚标记哪些是本次编译、哪些复用稳定产物。
JP6 本案例只打入 `.isp`；R39 本案例使用 `.nito` 和对应 Argus 配置。

### 3. 核对真实模块 ABI 与依赖

使用自带脚本检查未压缩 ARM64 `.ko`。它支持本案例 5.15 固定长度和 Ubuntu 6.8 变长
`__versions`，不加载模块，也不修改被检查的 rootfs：

```bash
python3 scripts/audit_module_abi.py --kernel "$KREL" \
  --symvers "$KERNEL_SYMVERS" --symvers "$MATCHED_OOT_SYMVERS" \
  --provider-module "$ACTUAL_CAMERA_KO" \
  --module "$NEW_SL_ZEDX_KO" --output ./sensor-abi.json
```

`--provider-module` 提供从实际模块读取的导出 CRC，优先于符号表。同名符号变化会进入报告。
该脚本校验 CRC，不替代头文件类型/结构体布局校验。

最终包解开到合并了目标依赖、已运行 `depmod -b` 的**临时 rootfs**后，再执行：

```bash
python3 scripts/audit_module_abi.py --kernel "$KREL" \
  --symvers "$KERNEL_SYMVERS" --symvers "$MATCHED_OOT_SYMVERS" \
  --root "$STAGED_ROOT" --module "$STAGED_SL_ZEDX_KO" \
  --module "$STAGED_BMI088_KO" --module "$STAGED_BMI_SPSC_KO" \
  --output ./dependency-abi.json
```

脚本检查实际选择路径/摘要、每个声明的模块依赖、完整依赖闭包及实际模块导出 CRC。
按最终 manifest 添加其余包内模块作为 `--module`，保证无遗漏。
从 `/lib/modules` 和 `/usr/lib/modules` 两种解包位置合并依赖，不能只看 depmod 的退出码。

### 4. 打包并验证

原流程逐载板顺序打包，避免共用 staging/control 竞争。检查**解开的实际 deb**，
而不只检查源码树：模块摘要与最终 manifest 一致、内核和 L4T 依赖边界、
ARM64 daemon 及目标 GLIBC 兼容性、服务/维护脚本、当前载板 DT、调参文件、
全 SKU overlay 合并、extlinux 可重复写入/备份及升级后服务仍完整。

对沿用 1.4.4.4 分配函数的适配，执行实际 C 逻辑回归：

```bash
ZEDX_PIPE_SOURCE="$MAX96712_SOURCE" python3 scripts/test_pipe_allocation.py
```

此回归适用于该函数签名和数据结构；新上游重构后应适配测试桩，不能为了测试通过改回驱动逻辑。

### 5. 实机验证与交付

按授权先保存初始状态，再验证枚举、每台 SDK 收帧、图像取回、多机并发、关闭重开、
IMU、Studio GUI，以及约定时长的持续运行。安装后冷启动/正常重启验证与热加载验证分别记录。
GPU/Argus 处于 D 状态时先保存线程栈和首发日志；重启恢复不算新代码修复的证据。

交付对应载板 deb、实际使用的源码/补丁、manifest、构建命令、依赖来源、离线/实机结果与 SHA256SUMS。
缺失的外部依赖明确列出，避免把不能独立重编译的源码包称为完整可复现环境。
