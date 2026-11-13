# Seeed-Jetson-Skills

A curated collection of AI agent skills for developing with Seeed reComputer and NVIDIA Jetson. Skills are split by where the work runs: `host/` contains PC-side remote, BSP, flashing, and board bring-up workflows; `device/` contains workflows performed on a running Jetson.

## Contents

- `host/seeed/` — Seeed-specific host and remote skills from the Develop Tool bundle.
- `host/codex/` — additional Jetson host skills found in the local Codex library.
- `host/nvidia/jetson-bsp-skills/` — full upstream NVIDIA BSP skills snapshot, including its references and license.
- `device/seeed/` — Seeed Jetson software, applications, and troubleshooting skills.
- `device/codex/` — additional Jetson device skills found in the local Codex library.
- `device/nvidia/jetson-device-skills/` — full upstream NVIDIA live-device skills snapshot, including its installation files and license.
- `sources/sources.json` — upstream revisions, retrieval date, and Codex additions.

Each skill directory contains its original `SKILL.md` and supporting files. See [LICENSES.md](LICENSES.md) for collection-level attribution guidance; individual upstream license files remain alongside their snapshots.

## Use a skill

Open the relevant `SKILL.md` and follow it with a compatible agent. NVIDIA’s original install scripts are kept inside their source snapshots. For Seeed and Codex skill directories, copy the entire skill folder into the skill directory used by your agent (`~/.codex/skills`, `~/.claude/skills`, or another compatible location).

## Refresh NVIDIA sources

The NVIDIA snapshots are pinned to the revisions recorded in `sources/sources.json`. To refresh them, clone or update the upstream repositories and replace the corresponding source snapshot directories, retaining upstream license and reference files.

## 分类说明

本仓库汇总 Seeed Jetson Develop Tool、自带的本机 Codex Jetson 技能，以及 NVIDIA Jetson 官方 BSP 和设备端技能。`host/` 放在 PC 上执行的远程连接、烧录、BSP/驱动和板级支持包工作；`device/` 放在 Jetson 启动后的系统诊断、软件部署、AI 应用与设备配置。
