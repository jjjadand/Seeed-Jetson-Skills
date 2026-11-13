# GDM 登录标识：已定位的失败原因与处理

本记录来自 2026-11-05/06 的 Jetson Orin Super J401 MFI 镜像检查。所述 GNOME 46 逻辑和 NVIDIA 配置来自目标镜像，后续版本应读取当前包确认。最终 Logo 版本已完成离线校验；本记录不代表用户已确认实机画面。

## 两个相互独立的问题

目标 `/etc/systemd/system/gdm.service.d/override.conf` 含：

```ini
[Service]
ExecStartPre=
```

这清除了发行版 GDM 的 `/usr/share/gdm/generate-config`。后者本应把 `/usr/share/gdm/dconf` 编译到 `/var/lib/gdm3/greeter-dconf-defaults`。只写入新 keyfile，或者单独运行 `dconf update`，不保证这个 file-db 被更新。

另外，目标 `usr/lib/gnome-shell/libshell-14.so` 内的资源 `/org/gnome/shell/gdm/loginDialog.js` 显示：`_showUserList()` 调用 `_hideBannerView()`。普通 banner 在最初的用户选择页会隐藏；GDM 的独立 `_logoBin` 则作为登录对话框子节点继续显示。

因此采用：透明 PNG 内绘制一行醒目文字；配置 logo（目标 schema 支持时也设置 fallback-logo）；关闭重复 banner；嵌入已编译数据库；在 NVIDIA reset 之后添加 root `ExecStartPre=+...` 重新编译。Logo 的具体位置受目标 GNOME 主题影响，不应保证所有版本都在相同像素位置。

## 保留目标设置

典型 profile：

```text
user-db:user
file-db:/var/lib/gdm3/greeter-dconf-defaults
```

在主机用临时 profile 读取目标数据库，避免误改主机桌面：

```bash
printf '%s\n' "file-db:$inspection_dir/var/lib/gdm3/greeter-dconf-defaults" > "$inspection_dir/read-profile"
DCONF_PROFILE="$inspection_dir/read-profile" dconf dump /
```

把原数据库 dump 保存为保留设置的 keyfile，再覆盖用户要求的 logo 相关键。编译时同时保留目标 keyfile 及 locks，处理 `/usr/share/gdm/dconf/90-debian-settings` 指向 `/etc/gdm3/greeter.dconf-defaults` 的绝对软链接；不要让这个软链接意外读取主机文件。

缓存数据库属主、实际 GDM 用户和显示管理器别名必须从本次包读取。示例曾是 UID 121/GID 122，但工具替换现有数据库时保留原 tar header 中的属主，不固定这些数字。若存在 GDM 用户数据库，检查其中是否有 logo 覆盖值。

本技能生成的 helper 在 dconf 编译失败时保留镜像内预置数据库，避免仅因刷新配置失败阻断图形登录。helper 本身的实际启动顺序仍需检查，不能只看文件名。

## APP 归档与安装边界

预制 MFI 常见 `rootfs/` 为空，APP 名称仍可能是 `nvme0n1p1_bak.img`，但内容为 zstd 压缩 tar。由实际 `flash.cfg` 和索引确定镜像；工具同时支持任意普通 APP 文件名及保存的 sda/NVMe 配置。

对普通 tar 文件替换大小时，仅修改该记录的 size/checksum 字段、内容及 512 字节填充。保留前置 PAX header 和其他区域；若 PAX 自身覆写 size 或待改路径是链接，必须先适配。新文件在第一个结束标记前加入，不能追加到 tar 的零填充之后。归档中同一路径重复出现时应先分析，不能假定第一次记录就是最终生效的文件。

APP 索引里的容量代表分区布局，不应换成压缩文件大小。只更新该 APP 行的 SHA1 和镜像 `.sha1sum`；其他分区、DTB 和签名启动二进制不随标识改变。GNU tar 的实际提取参数包括 `--numeric-owner --xattrs --xattrs-include=*`。离线验证可用 `--no-same-owner` 在临时目录提取，归档 UID/GID 则另外核对。

同文件系统硬链接备份不额外复制整个旧镜像；原子替换后新旧 inode 分离。硬链接并非独立介质备份，也不能抵御外部清理。曾出现安装后原 APP 备份从目录消失而记录仍保留的情况，因此安装器及结束报告都应核实备份当前存在且校验正确；不要自动清理它。

## 验证范围

离线检查应覆盖数据库读取、保留原设置、服务合并顺序、脚本编译/失败回退、完整 zstd 流、GNU tar 提取、未修改字节、索引一致性及备份。实机画面需要目标启动后另行确认。没有目标密码时不要猜测凭据、重置密码或承诺已验证画面；也无需为离线修改要求插调试串口。

若用户只要求登录页标识，终端 MOTD、交互 bash、桌面壁纸和锁屏保持各自独立范围。若用户明确要求多个位置，再分别实现并验证，避免七行 ASCII art 或同一页面多处重复文字。
