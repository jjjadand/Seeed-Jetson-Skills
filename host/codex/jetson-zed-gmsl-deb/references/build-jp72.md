# JP7.2 / R39.2.0 / 6.8：构建与原版打包

本方法复现 T234 J501 的已保存版本，不声称支持所有 JetPack7 载板或未来相机型号。
基线和模块来源见 [j501-baselines.md](j501-baselines.md)。

## 输入与工具链

使用匹配的 R39.2.0 BSP、6.8.12-1021-tegra 生成头文件/配置/Module.symvers、
NVIDIA OOT、hwpm、conftest，以及 GCC13.2 ARM64 工具链/sysroot。
T234 运行本版本不表示要使用 tegra264 DT。参考发布包目标用户态为 Ubuntu24.04。

将路径绑定为实际存在的目录：

```bash
export ZED_DIR=/path/to/zed-workspace
export BSP=/path/to/Linux_for_Tegra
export OOT="$ZED_DIR/seeed-upstream-r39.2.0/source/nvidia-oot"
export KBUILD=/path/to/prepared/kernel-noble
export CROSS_COMPILE=/path/to/aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu-
export BASE_DTB_DIR=/path/to/matching/base-dtbs
test -f "$KBUILD/Module.symvers"
test -x "${CROSS_COMPILE}gcc"
```

不要对工作区中所有同名 `.ko` 做通配拷贝；从 manifest 反查发布模块，排除旧 CSI guard、
HDR/UHD 等试验输出。保存的稳定源位于 OOT 树，旧 `src/kernel/stereolabs` 不是本版本来源。

## 模块集与构建策略

本案例同一构建的 10 个模块：

- ZED：`sl_max96712`、`sl_max9295`、`sl_zedx`。
- IMU：`bmi088`、`bmi_spsc`。
- 配套核心：`tegra-camera`、`tegra-capture-isp`、`tegra-capture-coe`、`capture-ivc`、`ivc-bus`。

初次适配或改变公共接口时，使用该 BSP 的 NVIDIA 顶层 Kbuild/nvbuild 流程构建匹配的
相机 OOT 依赖集，并保留完整命令/日志。顶层构建参数来自该 release 自带 Makefile，
不能从另一个 L4T 的路径结构推断。

稳定基线中只修改 MAX96712 分配函数、且它的 15 个导出 CRC 不变时，可按历史记录增量编译：

```bash
make -C "$KBUILD" ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" \
  M="$OOT/drivers/media/i2c/stereolabs/max96712" CONFIG_SL_DESER_MAX96712=m \
  EXTRA_CFLAGS="-I$OOT/include -I$BSP/source/kernel_out/out/nvidia-conftest -Werror -Wmissing-prototypes -Werror=declaration-after-statement" \
  KBUILD_EXTRA_SYMBOLS="$BSP/rootfs/usr/src/nvidia/nvidia-public/Module.symvers" \
  -j8 modules
```

conftest 路径要以实际构建输出为准。上式不代表其余九个模块被本次重编译；它们只能来自
已验证的同一构建。核对所有模块的实际依赖 CRC，再调用 package.sh。

Ubuntu6.8 的 `__versions` 在该内核中使用变长记录，旧主机 kmod 可能无法正确解码。
使用技能 `audit_module_abi.py` 或已验证的发布校验器；解析失败不能跳过 CRC 检查。

## Daemon 与 NITO

```bash
cd "$ZED_DIR"
./build_Daemon_CC.sh 392
```

检查三个产物 ARM64 ELF 及目标 GLIBC/GLIBCXX/CXXABI，不复用 JP6 不明来源二进制。
原脚本可能用 `Daemon/.DAEMON_39.2` 缓存编译状态；源码变更后验证缓存和二进制确实刷新。

R39 发布 payload 使用 AR0234 NITO，不把旧 `.isp` 当作同等替代。该案例 Argus drop-in：

```ini
[Service]
Environment=NVCAMERA_NITO_PATH=/var/nvidia/nvcam/settings/zedx_ar0234.nito
```

保留设备已有的多机 timeout 等配置，避免覆盖整个 Argus service。调参 badge、文件与
SDK 模式需对应；其他 sensor 型号需取得兼容 tuning，不能仅重命名 AR0234 文件。

## DT 与打包

DT 使用对应载板的 Seeed `source/hardware/.../overlay` 和匹配 base DTB。
更改源码后先重编 DTBO；`ZEDX_SKIP_BUILD=1` 应拒绝早于输入源的过期产物。

```bash
cd "$ZED_DIR"
export ZEDX_SKIP_BUILD=1
export ZEDX_DRIVER_ROOT="$OOT/drivers/media/i2c/stereolabs"
export ZEDX_NVIDIA_OOT_OUT="$OOT"
export ZEDX_BASE_DTB_DIR="$BASE_DTB_DIR"
export ZEDX_BUILD_MANIFEST=/path/to/final/BUILD_MANIFEST.json
./package.sh -ov \
  -dt "$ZED_DIR/seeed-upstream-r39.2.0/source/hardware/nvidia/t23x/nv-public/overlay/tegra234-stereolabs-zedx-j501-mini-overlay.dts" \
  -n zedx-j501-mini
./package.sh -ov \
  -dt "$ZED_DIR/seeed-upstream-r39.2.0/source/hardware/nvidia/t23x/nv-public/overlay/tegra234-stereolabs-zedx-j501-overlay.dts" \
  -n zedx-j501-robo
```

这些是保存的 ZED 工程扩展参数，不能假定任意上游 package.sh 已支持。
给新载板适配时保留原入口和 Debian rules，按实际需要移植这些参数支持。

本版核心替换模块放到 `updates/zedx-j501`，ZED 模块位于
`kernel/drivers/stereolabs`；通过 depmod override 选择匹配的配套版本。
必须校验 dry-run 实际路径，不能仅凭 `modinfo` 显示同一版本字符串。
其他内核/载板不必机械替换这五个核心模块；按 ABI 和必要功能确定最小配套集。

## 重现级别

- **重打包复现**：原始 10 个 ko、daemon、DTBO 和 base DTB 重新进入原 package.sh。
  包压缩时间戳可变化，按解开的安装文件/摘要对比。
- **源码重编译复现**：必须另外保有实际头文件、配置、symvers、编译器和全部构建依赖。
  当前本地完整归档 checkout 未含原 `dependencies/`；没有恢复依赖时只报告前一级。

manifest 的旧绝对路径或早期 `package_version/hardware_tested` 可能继承自历史候选包。
最终交付另出准确的版本/源码/验证记录；不可静默修改原件然后声称原始 SHA 未变。
