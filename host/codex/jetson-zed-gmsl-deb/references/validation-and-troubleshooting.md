# 包验收、实机分层定位与交付

## 实际 deb 检查

在临时目录用 `dpkg-deb -x/-e`，不执行目标 `postinst`。逐项记录：

- control 的 Package/Version/Architecture、精确 L4T/kernel/RT 依赖及不同板互斥关系。
- 每个 ko 的 ARM64、vermagic、SHA256、import CRC；最终 manifest 与实际包匹配。
- 含全套目标依赖的临时 rootfs 上 depmod 选择路径、所有 `depends` 和实际导出 CRC。
- daemon ELF 与目标库的 GLIBC/GLIBCXX/CXXABI 版本；编译时使用正确 `L4T_VERSION`。
- tuning 类型正确（本案例 JP6 ISP、R39 NITO），对应 badge 与 sensor，服务模板非空。
- 只包含当前载板 overlay 和有 provenance 的 base DTB；合并每个支持 SKU，核对路由与 IMU。
- `bash -n` 三个维护脚本；extlinux 重复安装、备份与中断写入场景；upgrade 不能走 remove/purge 清理。

服务模板放在包拥有的 `/usr/lib/stereolabs/.../services`，postinst 完整写入临时文件，
比对、落盘、原子替换到 `/etc/systemd/system`，reload 后确认 LoadState=loaded。
只在有对应 release 修复且确有需求时替换 ISP 库；不能打包不匹配的旧 `libnvisppg.so`。

本技能 ABI 脚本用法见 `python3 scripts/audit_module_abi.py --help`。
它不代替 DT、用户态或硬件检查，也不证明供应商头文件语义正确。

## 根据最早失败阶段定位

| 表现 | 第一轮证据 | 后续处理 |
| --- | --- | --- |
| deb postinst 失败，无法唯一选 DTB | extlinux、carrier、SKU、DTB 内容摘要 | 修复选择规则并实际合并，不取第一个文件 |
| 无 video，SerDes/IMU 也未探测 | 生效 DT、GPIO/I2C、供电与模块日志 | 比对物理接线，先排 DT/控制链路 |
| SerDes 识别相机但 sl_zedx 未加载 | dmesg `disagrees/Unknown symbol`、实际 camera exports | 正确 headers+symvers 重编译，不能 force |
| video 正常，但部分 open/grab 失败 | pipe 分配、VC/CSI/VI、link/video lock、首发 CSI/RCE 错误 | 核对每条实际数据路由和 source/target pipe |
| SDK 可枚举但不能创建会话 | Argus 首轮日志、badge、tuning、占用客户端 | 先结束竞争客户端并确认会话，不把枚举当作收帧 |
| 多机短时流后全部断开 | FROZEN/Argus NRestarts、IMU I2C、线程状态 | 比较首发与恢复后错误，避免反复全局恢复掩盖原因 |
| Argus 停止超时且线程 D 状态 | `/proc/PID/task/TID/stack`、GPU/DCE、boot ID | 保留证据；按已有授权恢复整机并抓首轮日志 |

J501 已知 pipe 例子：两台 One+两台双目需要六个独立目标 pipe，旧错误只启用三条。
`No Camera` 的备用 bus 和 `bmi088 probe -5` 必须与接线对应；用户移动过排线时，
先记录 bus/相机序列号变化，不能把 bus7→bus3 自动归因为驱动随机异常。

I2C 地址冲突、pipe 分配错误、ABI 拒载和 GPU/DCE 阻塞是不同故障类别，分别用证据判定。
不要同时改 lane polarity、I2C aliases、IMU 和 CSI 速率，造成无法对照。

## 实机验证顺序

在当前任务已授权操作范围内：

1. 保存 boot ID、内核/包/运行模块、引导配置、连接方式、首轮日志和活跃相机客户端。
2. 安装前保存旧包/模块与 extlinux；安装后核对 dpkg 状态、包内文件 hash 和服务。
3. 先检查物理相机数、video/subdevice、media graph、SerDes pipe、IMU；双目 video 数与物理相机数不同。
4. 单机 SDK 打开、抓帧、取回实际图像；记录型号、序列号、分辨率/fps、帧数、IMU、深度模式。
5. 按每个支持型号/端口逐台验证，再逐台增加和并发验证；用当前 SDK 编译诊断程序。
6. 关闭重开、冷启动/正常重启、反复运行、Studio GUI 与约定时长的稳定性各自验证。
   `DEPTH_MODE=NONE` 的通过结果不等于所有深度/GUI 管线通过。

热加载适合作为 ABI 修复因果验证，但不是安装后冷启动验收。不要为了完成“构建”任务自动
停止用户正在使用的相机或重启；已有明确授权则继续，不重复请求同一授权。
在 headless SSH 下启动 Studio 需先核对真实桌面会话 DISPLAY、XAUTHORITY/Wayland 和用户身份。

### 保存的 SDK 5.5.1 抓帧例子

`assets/sdk_single_stereo_probe.cpp` 与 `assets/sdk_multi_probe.cpp` 是本次实机曾用的源码。
在目标机（不是缺少 SDK 的 x86 构建主机）用其 SDK/CUDA headers 和库重新编译：

```bash
g++ -std=c++17 -O2 sdk_single_stereo_probe.cpp -o sdk_single_stereo_probe \
  -I/usr/local/zed/include -I/usr/local/cuda/include -L/usr/local/zed/lib \
  -Wl,-rpath,/usr/local/zed/lib -lsl_zed -pthread
g++ -std=c++17 -O2 sdk_multi_probe.cpp -o sdk_multi_probe \
  -I/usr/local/zed/include -I/usr/local/cuda/include -L/usr/local/zed/lib \
  -Wl,-rpath,/usr/local/zed/lib -lsl_zed -pthread
timeout -k 5s 45s ./sdk_single_stereo_probe "$STEREO_SERIAL"
timeout -k 5s 60s ./sdk_multi_probe 300 "one:$ONE_SERIAL" "stereo:$STEREO_SERIAL"
```

单机程序默认只列出双目 Camera 设备；传入序列号后测 300 帧 HD1200@30，取回第一张 CPU 图像。
多机程序要求至少两台：One 使用 HD1200@15、双目使用 HD1200@30，记录每台 open/grab 结果。
这些默认模式是历史测试参数，新型号需改成支持的模式；CameraOne API 取决于 SDK。
两个程序的深度为 NONE，不能作为 GUI/深度稳定性测试；首帧图像尺寸/返回码需从日志另行判断。
先确认没有其他客户端使用相机，再按当前授权执行。超时退出可能留下待恢复的 Argus 状态，保存日志后判断。

若 Argus 已经 D-state：服务重启/SIGKILL 不保证释放 GPU 引用。保存首次报错、线程栈后，
使用授权的恢复方式，恢复后用同包/同接线对照；记录“运行状态恢复”而不是捏造代码修复。

## 发布记录字段

`assets/port-record.template.json` 是可以复制后填写的记录模板，null 表示未确认。
把构建输入 manifest 与后续硬件结果分开：包生成后在硬件结果文件中补测试，避免修改已嵌入包内的 manifest 导致摘要不一致。

至少交付：

- 每板 deb、buildinfo/changes、SHA256SUMS；原稳定包保留原件。
- 实际源码快照与每个仓库 commit、dirty diff、补丁、全部额外头文件和 DT inputs。
- 编译器/sysroot 版本、配置、所有使用过的 Module.symvers 和实际 provider hash。
- 完整构建/打包命令和日志，哪些模块编译/复用；未附带的依赖及恢复方法。
- 离线检查、目标机证据、实际相机组合与每项测试结果；尚未执行的项目直写未测试。

代码、配置、patch 或模板不能保存密码、token 或依赖固定现场 IP。跨机器重现使用显式路径参数。
仅重新压缩包时 deb SHA 可能变化，应同时比较解出的实际安装文件；如果宣传字节可重复，
还需固定构建时间戳、编译路径、工具版本并实际做字节比较。
