---
name: jetson-mfi-flash-fix
description: "诊断和修复 Seeed Jetson Orin MFI/initrd 量产烧录包中的 basename 缺失、误写 /dev/2、失败误报成功、板级配置缺失及 flash-only 参数解析问题；支持保留 tar xpf 解压兼容性的重新打包与压缩包校验。适用于已有预制 MFI 包，不用于通用 BSP 构建或硬件刷写超时。"
---

# Jetson MFI 烧录包修复

针对已验证的 `recomputer-orin-super-j401` 预制 MFI 包，修复文本脚本并保留刷机镜像。工具均相对于技能目录定位资源，不依赖原先的 `/home/darklee/mfi-j401-fix` 临时补丁目录。

## 识别本次问题

出现以下链路时使用本技能：

```text
basename: command not found
blkdiscard -f /dev/2
dd if=/dev/zero of=/dev/2
No space left on device
Writing nvme0n1p2 partition done
Successfully flashed the external device
```

缺失 `basename` 会让设备名变空，分区号被拼成 `/dev/2` 等路径；`dd` 可在 `/dev` 创建普通文件，最终的 success 因错误返回被掩盖而不可信。改变主机工作目录不能补上目标机 initrd 中缺失的程序。

详细证据、配置缺失、`udevadm` 提示的边界见 [references/incident.md](references/incident.md)。仅需重新压缩或判断 tar 警告时，直接读 [references/repack.md](references/repack.md)。

## 修复已有 MFI 包

1. 使用用户指定的目录，读取适用的 `AGENTS.md`。检查 `initrdflashparam.txt`、`initrdflashimgmap.txt` 和实际日志。量产命令通常复用 `bootloader/boot0.img`，实际运行的是 NFS 下的 `tools/kernel_flash/images/l4t_flash_from_kernel.sh`，不能只改上层副本。
2. 将 `skill_dir` 设为本 `SKILL.md` 所在目录，`mfi_dir` 设为待修复目录。先做只读预检：

   ```bash
   bash "$skill_dir/scripts/apply.sh" --check "$mfi_dir"
   ```

   脚本只接受资源中原始版本或已修复版本，拒绝覆盖其他版本。预检不通过时，依据 [assets/repair/changes.patch](assets/repair/changes.patch) 对照差异，保留现有定制并适配修复；不要跳过版本检查强行覆盖。
3. 用户已要求修复且预检通过时，直接应用并验证：

   ```bash
   sudo bash "$skill_dir/scripts/apply.sh" "$mfi_dir"
   python3 "$skill_dir/scripts/verify.py" --installed --target "$mfi_dir"
   ```

   应用脚本先备份到包内 `.mfi-fix-backup-*`，再原子替换四个文本文件，失败时恢复原文件。需要权限时沿用当前会话授权；不保存密码或把过往凭据写入命令文件。此操作不会启动烧录。

修复范围：

- 两份 `l4t_flash_from_kernel.sh`：用 `${device##*/}` 取设备名，拒绝空设备名与非法分区号；擦写前检查块设备；清零只写设备容量；显式传递擦除、解压和写入失败。Bash 函数在调用方 `if ! function` 中时不能依赖 `set -e` 自动退出。
- `recomputer-orin-super-j401.conf`：完整 BSP 优先加载原基础配置；识别出预制 MFI 包后，用包内 `p3767.conf.common` 提供 `CHIPID=0x23`。此回退仅支撑已有镜像的 flash-only，不能作为生成新 BSP 镜像的完整板级配置。
- `l4t_initrd_flash.sh`：`--flash-only` 首次加载配置前，从保存的参数文件读取板卡名，支持不带板卡位置参数的量产命令。

验证脚本执行 23 项模拟检查，覆盖分区路径、错误返回、普通文件拒写、有限清零和下列原始命令的参数解析；不会打开真实块设备。不同版本手工适配时，需检查验证脚本的函数提取和路径假设仍成立。

```bash
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0 --showlogs
```

报告备份位置、检查结果以及是否做过实机烧录。修复包后是否启动烧录以用户当前任务为准；不要把模拟检查描述为实机烧录成功。此前已误写的那次操作需要设备重新进入 Recovery 后完整重刷。

## 打包和归档验证

保留单个 `./mfi_recomputer-orin-super-j401/` 顶层目录、文件权限和软链接。若用户只要最简命令，给出命令即可，不必替用户打包。当前目录是 MFI 包时可用：

```bash
sudo tar -czf ../mfi_recomputer-orin-super-j401-fixed.tar.gz -C .. ./mfi_recomputer-orin-super-j401
```

该命令包含包内全部内容，符合用户本次“不排除”的选择；排除备份或日志应按当前用户需求决定。不要改成 `-C .. .`，那会打包整个父目录。GNU tar 可继续用 `sudo tar xpf archive.tar.gz` 解压。

遇到“文件发生了变化”时，不凭警告断言可用或损坏。先确认压缩已结束，再按 [references/repack.md](references/repack.md) 运行完整流校验；[scripts/verify_archive.py](scripts/verify_archive.py) 会验证 gzip CRC、归档路径和重复条目、四个修复文件内容，以及当前 MFI 文件的存在性与大小。额外顶层目录只代表多打包了内容，单独说明即可。
