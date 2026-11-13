---
name: jetson-bt-wifi-fix
description: Fix Jetson Bluetooth disconnect issues when Wi-Fi is active by running an auto-maintain reconnect script with clear start, stop, and verification steps.
metadata:
  short-description: Fix BT/Wi-Fi coexist
---

# Jetson BT Wi-Fi Fix Skill

## Trigger
Use when user reports Bluetooth instability while Wi-Fi is in use on Jetson.

## Workflow
1. Confirm at least one successful manual Bluetooth pairing.
2. Run `bt-auto-fix.sh` in foreground or background.
3. Validate connected devices and link stability.
4. Provide safe stop and cleanup command.

## Deterministic Commands
```bash
bash ../../shared/scripts/bt-auto-fix.sh
nohup bash ../../shared/scripts/bt-auto-fix.sh >/tmp/bt-auto-fix.log 2>&1 &
test -f /tmp/bt-auto-maintain.pid && kill "$(cat /tmp/bt-auto-maintain.pid)"
```

## Output Contract
- start command and mode (foreground/background)
- verification commands and expected outputs
- stop command and fallback actions

## References
- `../../shared/references/bt_wifi_coexist_fix.md`
- `../../shared/references/troubleshooting_checklists.md`
