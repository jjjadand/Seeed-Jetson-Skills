# JP6.2.1 / R36.4.4 / 5.15：匹配 Seeed ABI

本案例正式使用 `1.4.4.4+seeed1-L4T36.4.4`。初版无 `+seeed1` 的 JP6 包有已证实的
ABI 问题，不作为新载板参考产物。JP6.2 其他 L4T 修订需重新确认，不能直接改 control 版本号。

## 先核对实际 camera 核心

```bash
uname -r
cat /etc/nv_tegra_release
modinfo -n tegra_camera
modprobe --show-exports "$(modinfo -n tegra_camera)"
```

同名 `5.15.148-tegra` 和 `36.4.4` 不够。目标 `/usr/src/nvidia/nvidia-oot/Module.symvers`
仍可能是 NVIDIA 原版，而 Seeed 实际 ko 已修改。将真实 camera ko、匹配头文件/源码、
镜像提交和 hash 保存到构建记录。磁盘模块与已加载模块有可能不同；升级后保存加载前后
boot ID/模块信息，并按授权执行冷启动或明确的重新加载验证。

J501 的固定例子（不是新板通用 CRC）：

| 接口 | NVIDIA 官方要求 | J501 Seeed 真实导出 |
| --- | --- | --- |
| tegracam_v4l2subdev_register | 0x9bba14c6 | 0xa0dc905b |
| tegracam_v4l2subdev_unregister | 0x8e09dd0b | 0x3afeabf2 |
| tegracam_device_register | 0xaa061119 | 0xe429db70 |
| tegracam_device_unregister | 0x2952e80a | 0x683125a0 |
| tegracam_set_privdata | 0x31a33147 | 0x2a6815c3 |
| tegracam_get_privdata | 0x7bd9e57c | 0xd68f3c04 |
| camera_common_mclk_enable | 0x8cf65332 | 0xf321438e |
| camera_common_mclk_disable | 0x22e1008c | 0x6c7d2b94 |

Seeed `camera_common.h` 的 `tegracam_ctrl_ops.set_trig_mode` 在偏移168，结构体176字节；
官方168字节。用匹配头文件重新编译，结合实际 ko 导出重建对应 provider symvers。
不能只改 symvers/ko CRC 来绕过检查；结构体大小/成员偏移也必须匹配。
有 DWARF 时可用 pyelftools/pahole 或编译布局探针对比；编译探针需要完整类型调试信息
（历史使用 `-g -femit-struct-debug-detailed=any -fno-eliminate-unused-debug-types`）。

提取真实导出形成 Kbuild 输入示例：

```bash
modprobe --show-exports "$ACTUAL_CAMERA_KO" > "$BUILD/camera.exports"
awk -v p="$ACTUAL_CAMERA_KO" '{printf "%s\t%s\t%s\tEXPORT_SYMBOL\t\n", $1,$2,p}' \
  "$BUILD/camera.exports" > "$BUILD/camera-actual.symvers"
```

这一步不辨别 GPL/namespace，以上仅用于已审查接口的 CRC 输入；发布记录保留原 provider 信息。
与 NVIDIA OOT 符号表合并时，按 symbol 替换，保留其余元数据和末尾空 namespace 的 TAB。
不要给 modpost 传入同一 symbol 的两份矛盾定义；去掉末尾 TAB 可能造成 symbol dump parse error。
完整构建仍应优先使用对应 Seeed 源码导出的真实 Module.symvers。

## 编译五个模块

输入为官方 R36.4.4 kernel headers、匹配 Seeed camera 接口的 OOT includes/symvers，
GCC11.3 ARM64 工具链/sysroot，对应 Ubuntu22.04 用户态。本案例不替换系统 NVIDIA/Seeed
camera/host1x 核心，不打入先前 36.4.3 的 ISP 共享库。

官方 headers 中有些 host 工具为 ARM64；在 x86 主机需要重新构建 fixdep、genksyms、modpost。
只读 headers 包不是完整 kernel source，`modules_prepare` 可能缺 VDSO 等源文件。
记录最终 OOT 构建结果，不能把有失败的准备日志写为全量内核编译成功。

```bash
export ZED_DIR=/path/to/zed-workspace
export KHEADERS=/path/to/prepared/r3644/kernel-headers
export BUILD=/path/to/isolated/seeed-abi-build
export CROSS_COMPILE=/path/to/bin/aarch64-buildroot-linux-gnu-
cd "$ZED_DIR"
make -C "$KHEADERS" ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" \
  M="$ZED_DIR/src/kernel/stereolabs" \
  srctree.nvidia-oot="$BUILD/nvidia-headers/nvidia-oot" \
  srctree.nvconftest="$BUILD/conftest" \
  KBUILD_EXTRA_SYMBOLS="$BUILD/nvidia-headers/nvidia-oot/Module.symvers" \
  -j8 modules
```

Makefile 启用 MAX96712、MAX9295、ZEDX、BMI088；旧 HDR/UHD 实验模块不要混入此稳定版。
新相机若需要额外驱动，必须重新增加对应源码、DT、tuning、依赖和型号专属验证，不能说五个模块覆盖所有 ZED。

单独 staging 本次输出，排除旧树中残留 ko：

```bash
for pair in max96712/sl_max96712 max9295/sl_max9295 zedx/sl_zedx bmi088/bmi088 bmi088/bmi_spsc; do
  install -D -m 0644 "src/kernel/stereolabs/drivers/stereolabs/$pair.ko" \
    "$BUILD/stereolabs/drivers/stereolabs/$pair.ko"
done
./build_Daemon_CC.sh 364
```

三个 daemon 均重新用 JP6 工具链编译，检查 GLIBC/GLIBCXX 符号依赖；不能复用 JP7 Ubuntu24.04
编译出的程序。保存的稳定 daemon 源保留 5s FROZEN/60s 恢复间隔。

## ISP、DT 与原版打包

本 release 使用 `ISP/*.isp`，实际 deb 不包含 `.nito` 或 NITO drop-in/environment。
源码目录已有 `.nito` 可以保留，但不能通过 `ISP/*` 通配误打进 JP6 包。
Mini/Robo overlay 以稳定 JP7 源为基础，针对 R36 使用 Argus 接受的 `position=front`。
GPIO、IMU 别名和 CSI 路由仍逐载板核对。

```bash
export ZEDX_SKIP_BUILD=1
export ZEDX_KERNEL_OUT="$BUILD"
export ZEDX_BASE_DTB_DIR="$BUILD/base-dtbs"
export ZEDX_BUILD_MANIFEST=/path/to/final/BUILD_MANIFEST.json
./package.sh -ov -dt src/hardware/stereolabs/tegra234-stereolabs-zedx-j501-mini-overlay.dts -n zedx-j501-mini
./package.sh -ov -dt src/hardware/stereolabs/tegra234-stereolabs-zedx-j501-overlay.dts -n zedx-j501-robo
```

原 package.sh 负责 `dpkg-buildpackage`。各板顺序构建，control/changelog/preinst 修改应在退出时恢复。
deb 精确限定 R36.4.4 与非 RT 5.15.148-tegra，包间冲突关系明确。

给目标 ABI 固定的候选包添加安装前 CRC 检查，在删除服务/改引导之前执行。
J501 `+seeed1` 的八项白名单不应硬编码给所有载板；根据该产物 manifest 和兼容接口生成。
此检查是防止再次装错 ABI 的提示，不替代运行态验证。

## 离线依赖验证要合并两种路径

从目标机复制模块基线，或校验 SHA 后解包精确版本依赖 deb。下面所有写入仅针对新建临时目录：

```bash
SCRATCH=$(mktemp -d)
mkdir -p "$SCRATCH/root/usr/lib/modules/$KREL"
mkdir -p "$SCRATCH/root/etc/depmod.d"
ln -s usr/lib "$SCRATCH/root/lib"
# 先合并参考模块，再解开待测 deb；不要覆盖真实 rootfs。
for tree in "$REFERENCE/lib/modules/$KREL" "$REFERENCE/usr/lib/modules/$KREL"; do
  if test -d "$tree"; then cp -a "$tree/." "$SCRATCH/root/usr/lib/modules/$KREL/"; fi
done
dpkg-deb -x "$DEB" "$SCRATCH/root"
depmod -b "$SCRATCH/root" -C "$SCRATCH/root/etc/depmod.d" -a "$KREL"
```

两条参考路径若是同一 usrmerge symlink 不影响结果；不同真实目录则两者都要合并，冲突路径要检查来源/hash。
使用真实 Seeed camera provider 导出而不是官方表覆写它，执行主 SKILL 的闭包校验。
