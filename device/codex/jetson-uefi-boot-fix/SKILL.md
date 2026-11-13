---
name: jetson-uefi-boot-fix
description: Repair Jetson boot target selection by updating UEFI BootOrder to prioritize target SSD/NVMe entries and verifying firmware boot configuration.
metadata:
  short-description: Fix UEFI boot order
---

# Jetson UEFI Boot Fix Skill

## Trigger
Use when Jetson does not boot from expected SSD/NVMe and boot priority needs correction.

## Workflow
1. Capture `efibootmgr` before changes.
2. Run UEFI boot-order script with explicit user approval.
3. Verify `BootOrder` changed as expected.
4. Report log location and reboot validation steps.

## Deterministic Commands
```bash
sudo efibootmgr
sudo bash ../../shared/scripts/uefiboot.sh
sudo efibootmgr
```

## Safety Contract
- mark as high-risk
- require explicit confirmation
- include rollback and verification instructions

## References
- `../../shared/references/uefi_boot_fix.md`
- `../../shared/references/troubleshooting_checklists.md`
