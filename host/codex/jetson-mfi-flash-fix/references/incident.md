# 记录：Orin MFI 包误写分区且误报成功

发现于 2026-11-02，两份包于 2026-11-02 / 2026-11-03 应用同一补丁：

- `/home/darklee/mfi_recomputer-orin-super-j401`
- `/home/darklee/jetson_bsp/mfi_recomputer-orin-super-j401`

它们是历史工作位置，不是脚本默认目标或后续操作授权。硬件日志含 `p3767-0003`、Tegra234、NVMe 外部存储，命令为：

```bash
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0 --showlogs
```

## 已证明的因果链

1. RCM、USB 网络和 SSH 已成功建立，GPT 已写入 NVMe，QSPI 也报告完成。故本例不是 NFS 不通或等待目标机启动超时。
2. APP 镜像先解包到 `/dev/nvme0n1p1`，后续 Zstandard 原始分区镜像走 `flash_partition` → `write_zstd_image`。
3. 旧脚本第 579 行调用 `device_name=$(basename "${device}")`。读取 `bootloader/boot0.img` 中的 gzip/newc initrd 发现它没有 `basename`。主机安装 coreutils 不会改变这个预制 initrd。
4. 设备名为空时 `get_partition "" 2` 返回 `2`，目标变成 `/dev/2`。`blkdiscard` 失败后，无界 `dd if=/dev/zero` 创建普通文件，直到 `/dev` 的内存文件系统空间耗尽。后续解压又写入同一个普通文件，实际 NVMe 分区未收到这些镜像。
5. 调用链在 `if ! do_write_storage` 内运行，Bash 的 `errexit` 受到抑制；函数最后的 `sync` / `return 0` 可掩盖此前失败，因此日志仍出现 `Successfully flashed the external device`。

独立模拟使用原始脚本复现了 `/dev/2`，修复后验证了 `/dev/nvme0n1p2` 至 `p15`，以及擦除、解压和写入失败的返回值。模拟不会写真实 `/dev`。

## 相关但不同的错误

- `p3768-0000-p3767-0000-a0.conf: No such file or directory`：生成 MFI 包的脚本只复制顶层目标 `.conf` 和 `*.common`，漏掉被 source 的基础配置。对已有镜像 flash-only，可通过包内 `p3767.conf.common` 提供工具需要的 CHIPID。完整 BSP 构建仍需完整基础配置。
- 无位置参数的命令在入口早期用倒数第二个参数推断板卡名，把 `usb0` 误当板卡名。应在初次加载配置前就读取 `initrdflashparam.txt`。
- `blockdev: cannot open /dev/mmcblk0boot0`：本例是 QSPI + NVMe，不能单凭该提示认定设备 eMMC 损坏。
- `udevadm: not found`：本例来自目标 initrd 中分区工具的辅助调用，GPT 创建随后完成。不能因此宣布所有环境下均无影响。若 GPT 或分区节点未出现，应独立诊断；本补丁不改造该预制 initrd。
- `WARNING: failed to import T264 module`、`Not supported type: mb2_applet`：原日志已越过这些提示继续 RCM boot，不能将其当作本例 `/dev/2` 误写的原因。

## 资源和适用版本

`assets/repair/original` 与 `patched` 保存四个完整文本文件；脚本自动逐字节核对已知版本。`changes.patch` 用于审阅与适配其他版本。资源保留原 NVIDIA 版权和许可证声明。

本补丁不生成新的 boot0.img，不修改 QSPI 或分区镜像，不改变启动签名。已确认原 initrd 的 GNU dd 支持 `iflag=count_bytes`、blockdev 支持 `--getsize64`。其他 initrd 版本应重新确认这些选项。

两份原包安装后都通过 23 项模拟检查；安装时未自动刷机。归档校验通过也只证明压缩流和所检查内容，不等同于硬件启动成功。
