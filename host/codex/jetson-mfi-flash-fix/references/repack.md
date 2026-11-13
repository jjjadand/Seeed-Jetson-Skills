# 保留原 tar.gz 的解压结构

原包成员以 `./mfi_recomputer-orin-super-j401/` 开头。GNU tar 创建归档时保留权限与软链接，不要使用 `-h` 解引用链接；root 解压时 `sudo tar xpf` 可以恢复归档中的权限及所有者，gzip 会自动识别。

当前目录为 MFI 包时，包含全部内容的最简命令：

```bash
sudo tar -czf ../mfi_recomputer-orin-super-j401-fixed.tar.gz -C .. ./mfi_recomputer-orin-super-j401
```

换成其他包名时，同步替换最后一个参数。输出位于 MFI 目录之外，避免自包含。不主动删除原压缩包；只有用户要求实际打包时才生成大文件，执行前检查可用空间及是否有正在修改包的烧录进程。

解压到一个空目录后可继续原流程：

```bash
sudo tar xpf mfi_recomputer-orin-super-j401-fixed.tar.gz
cd mfi_recomputer-orin-super-j401
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0 --showlogs
```

## “在我们读入文件时文件发生了变化”

本例用户执行的是：

```bash
sudo tar -czf ../NOS-JAI-mfi_recomputer-orin-super-j401-fixed.tar.gz -C .. .
```

`-C .. .` 表示整个父目录 `jetson_bsp`，包含额外的 Downloads、Source、bsp、builds、repos。输出也在该父目录内，创建归档会改变父目录元数据，可能产生 `tar: .: file changed as we read it`。GNU tar 通常识别并跳过正在输出的归档；不要据此保证任意警告都无害。目录变化和关键镜像在读取中发生变化，是不同情况。

先确认 tar/gzip 不再运行，再做流校验，不必解压十几 GB：

```bash
python3 "$skill_dir/scripts/verify_archive.py" \
  /path/to/archive.tar.gz \
  --mfi-dir /path/to/mfi_recomputer-orin-super-j401
```

该工具不解压到文件系统，读取完整 gzip 流以触发 CRC 校验，核对四个修复文件的 SHA256，检查当前 MFI 普通文件的存在性和大小，并报告额外顶层目录。若包里存在不可读目录（例如 root 备份），先用普通权限验证可读文件；输出会明确未核对的目录。需要覆盖这些文件时可用 sudo 运行工具。

没有本地 MFI 目录时，`gzip -t archive.tar.gz` 只能验证 gzip 流，不能证明修复脚本已打包或镜像内容正确。

本例压缩包全流校验通过，四个修复文件一致、MFI 文件齐全，所以可继续使用，额外目录只需告知用户。不要把这次结论套用到未校验的新归档。
