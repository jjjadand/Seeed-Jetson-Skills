---
name: jetson-mfi-login-branding
description: "为 Jetson 预制 MFI/initrd 烧录包添加或修改单行图形登录页 tag、文字 Logo，处理 NVIDIA GDM 覆盖配置及 GNOME 用户选择页横幅不显示的问题，并校验实际 APP 镜像。适用于输入密码前的 GDM 登录页；桌面壁纸、锁屏和终端提示需按用户指定位置另行处理。"
---

# Jetson MFI 图形登录页标识

将用户指定的单行文字做成 GDM Logo，写入真正刷入设备的 APP 镜像。可用于 `Jetson-AI`、`Jetson-GW` 等文字；不要固定文字、载板、用户名、UID 或主机路径。

## 确定修改位置与镜像

- 沿用会话里已确认的位置和文字。这里的已验证方法针对**开机后、输入密码前的图形登录页**，包括初始用户选择页。用户明确要求桌面壁纸、锁屏或终端时，按那个范围实施；仅在位置无法从上下文判断时澄清。
- 先读取目标目录适用的 `AGENTS.md`、保存的烧录参数和 `tools/kernel_flash/images/external/flash.cfg`。`rootfs/` 可能为空；编辑它不代表修改了 massflash 实际写入的系统。
- 检查目标包是否正在被烧录任务使用，避免在活动烧录过程中替换镜像。
- 本技能工具支持 `APP_ext` 指向的 **Zstandard 压缩 tar**，文件名即使是 `.img` 也按真实格式处理。raw/sparse ext4、加密镜像或其他显示管理器需要适配，不要直接套用。
- 保存载板、DTB、签名启动文件、外部设备类型、分区尺寸及偏移。登录标识修改本身不授权刷写硬件、重启、重置密码或顺便修改其他 BSP 配置。

首次使用时读 [references/gdm-and-mfi.md](references/gdm-and-mfi.md)，了解为什么单改横幅 keyfile 不起效、如何检查实际 GDM 数据库和服务覆盖顺序。

## 准备与验证

脚本在本技能的 `scripts/` 下，不依赖此前的临时工作目录。需要 Python 3.10+、`zstandard`、Pillow，以及主机 `dconf`、GNU tar、`fc-match`；显式提供 `--font` 时不需要 `fc-match`。优先使用已有依赖，不为此升级 Jetson/BSP。

`skill_dir` 为本技能目录，`mfi_dir` 为用户指定路径。选择同一文件系统、包目录之外的可写工作目录；预留约一个 APP 镜像加压缩余量。工具拒绝覆盖已有作业目录，不会自动删除旧备份。临时分区空间不足时，将命令的 `TMPDIR` 指向这个有余量的工作目录。

```bash
work_dir=$(mktemp -d "$(dirname "$mfi_dir")/jetson-login-XXXXXX")
python3 "$skill_dir/scripts/inspect_app.py" "$mfi_dir" --output "$work_dir/inspection"
python3 "$skill_dir/scripts/build_payload.py" --inspection "$work_dir/inspection" --output "$work_dir/payload" --tag 'Jetson-AI'
python3 "$skill_dir/scripts/prepare_app.py" --inspection "$work_dir/inspection" --payload "$work_dir/payload" --output "$work_dir/prepared"
```

`--tag` 使用用户给定文字。默认加粗青色 40px、透明背景、单行；可传 `--font-size`、`--color`、`--font`。用 `--id` 复用已有本技能标识的文件名，默认 `jetson-login`。查看 `payload/preview.png` 确认文字、尺寸和对比度；字体必须覆盖所用字符。

这些步骤只读取 MFI，生成：Logo、保留原设置的 keyfiles、预编译数据库、较晚加载的 GDM 服务 drop-in 和配置生成脚本。准备工具只替换必要 tar 记录并在结束标记前加入新文件，保留其他 tar 字节、PAX/xattrs、软硬链接和顺序；完整解压验证后生成新 APP、`flash.idx` 和 `.sha1sum`。

安装前必须结合 `inspection/report.json` 核对：

- 当前显示管理器确实使用 GDM；`usr/share/dconf/profile/gdm` 读取的数据库与新数据库一致。
- 按字典序合并目标单元和全部 drop-in，NVIDIA 的 `ExecStartPre=` 重置之后仍保留 `+/usr/local/sbin/<id>-prepare-login`。可在临时根目录运行 `systemd-analyze --root ... cat-config systemd/system/gdm.service`，不要操作主机实际 GDM。
- 若有 GDM 用户级 dconf 数据库、其他后置 keyfile、已有自定义标识或不同服务别名，检查是否覆盖新 logo。工具拒绝的版本或 PAX size/符号链接目标应适配，不能跳过检查。
- 新数据库保留原设置，Logo 及脚本可读/可执行；原数据库属主来自当前归档，不套用某次设备的 121:122。工具会验证数据库、解包内容和权限；服务合并还需上述针对目标的核对。

## 安装到 MFI 工作目录

用户已要求修改包时，完成准备和核对后直接安装；沿用现有权限授权，需要提权则用同一 Python 解释器的绝对路径执行 sudo。

```bash
python3 "$skill_dir/scripts/install_prepared.py" --work "$work_dir/prepared" --check
sudo /absolute/path/to/python3 "$skill_dir/scripts/install_prepared.py" --work "$work_dir/prepared"
```

安装器核对原文件、新文件及索引，保留原镜像硬链接和元数据，原子替换同文件系统的 APP 并同步两处 SHA1；发生可捕获错误时恢复镜像和元数据。三文件替换不是单个事务：若断电或进程被杀，先检查 `transaction.json` 和备份，再恢复整组文件，不能盲目重复安装。

最后重新核实实际 APP、APP 索引行和 sidecar 的 SHA1 一致，并检查备份文件仍存在且校验正确。不要仅凭曾经打印过“备份成功”承诺可回退。保留备份，除非用户要求清理。

报告修改目录、文字/位置、校验结果、实际备份位置，以及是否做过实机画面验证。离线验证不能表述为实机已显示。只有用户要求时才进一步刷机；原有 `--flash-only --massflash ...` 命令通常不需要改变。

## 相关问题与工具自检

用户同时要求排查 `sda`、`basename` 缺失、误写 `/dev/2` 或烧录失败误报成功时，可另用已安装的 `jetson-mfi-flash-fix`。保留当前载板与存储配置，不因提到 sda 就把 NVMe 改成 sda。

工具修改后的自检：

```bash
python3 "$skill_dir/scripts/test_workflow.py"
```

它使用临时小镜像验证 dconf、GNU tar、保留 PAX/链接/UID、更新 tag、同文件系统安装、校验同步及故障回滚；不访问真实块设备或修改现有 MFI。
