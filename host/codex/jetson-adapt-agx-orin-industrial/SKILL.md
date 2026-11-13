---
name: jetson-adapt-agx-orin-industrial
description: Adapt and validate custom Jetson carrier-board BSPs, especially Seeed J50/reServer/reComputer variants, for the Jetson AGX Orin Industrial P3701-0008 module (Chip SKU 00:00:00:90). Use when adding BOARDSKU 0008 support, fixing "Unrecognized module SKU 0008", debugging initrd-flash boot timeouts, creating carrier-specific 0008 DTBs, selecting industrial FSI/bad-page/QSPI layouts, or extending the same adaptation to another J50 carrier.
---

# Adapt AGX Orin Industrial

Adapt one carrier at a time. Preserve carrier-specific pinmux, pad voltage, UPHY, ODMDATA, peripheral nodes, and camera topology while replacing module-specific P3701 data with the Industrial equivalents.

## Establish the module identity

Treat this tuple as AGX Orin Industrial:

```text
BOARDID=3701
BOARDSKU=0008
CHIP_SKU=00:00:00:90
RAMCODE=4
```

Accept FAB and BOARDREV from EEPROM. Known hardware can report values such as `FAB=500` and `BOARDREV=U.0`; do not hardcode them in reusable board configs.

Use `scripts/print_module_info.sh` on a booted target. During flashing, trust the `Board ID(...)` and `Chip SKU(...)` lines printed by `flash.sh` over assumptions based on product names.

## Inspect the BSP baseline

Read these files before editing:

```text
p3701.conf.common
p3737-0000-p3701-0008.conf
jetson-agx-orin-devkit-industrial.conf
<carrier>.conf
source/hardware/nvidia/t23x/nv-public/nv-platform/Makefile
```

Run the read-only preflight checker:

```bash
scripts/check_industrial_support.sh <Linux_for_Tegra> <carrier-board-name>
```

Read `references/p3701-0008-adaptation.md` before changing a new carrier.

## Patch the board configuration

Add a `board_sku=0008` branch that selects all module-specific Industrial files:

```bash
RAMCODE=4
BADPAGEFILE="bootloader/badpage.bin"
FSIFWFILE="bootloader/fsi-lk.bin"
EMMC_CFG="flash_t234_qspi_sdmmc_industrial.xml"
EMMC_BCT="tegra234-p3701-0008-sdram-l4t.dts"
WB0SDRAM_BCT="tegra234-p3701-0008-wb0sdram-l4t.dts"
PMIC_CONFIG="tegra234-mb1-bct-pmic-p3701-0008.dts"
MISC_CONFIG="tegra234-mb1-bct-misc-p3701-0008-flash.dts"
MISC_COLD_BOOT_CONFIG="tegra234-mb1-bct-misc-p3701-0008.dts"
MB2_BCT="tegra234-mb2-bct-misc-p3701-0008.dts"
BPFDTB_FILE="tegra234-bpmp-3701-0008-<carrier-id>.dtb"
DTB_FILE="<carrier-p3701-0008>.dtb"
TBCDTB_FILE="${DTB_FILE}"
```

Keep the carrier's existing `PINMUX_CONFIG`, `PMC_CONFIG`, `ODMDATA`, and overlays unless hardware analysis proves they must change.

On R39/JetPack 7 BSPs, prefer the NVIDIA-provided `set_p3701_0008_industrial_args` helper when it exists. Let `p3701.conf.common` select the 0008 SDRAM/WB0 BCTs during board-version processing, then override only carrier-specific values such as `DTB_FILE` and a no-CVB-EEPROM `MB2_BCT`.

### Avoid the early common-config rejection

Many carrier configs source `p3737-0000-p3701-0000.conf.common`. Its `update_flash_args_common` can reject SKU `0008` before the carrier's later SKU branch runs.

Special-case `0008` before calling that common function:

```bash
update_flash_args()
{
    if [ "${board_sku}" = "0008" ]; then
        BPFDTB_FILE="tegra234-bpmp-3701-0008-<carrier-id>.dtb"
    else
        update_flash_args_common
    fi
    update_flash_args_<carrier>
}
```

Do not globally relax the common config unless every carrier sourcing it has been validated for Industrial modules.

## Create the carrier DTB

Create a separate 0008 DTS. Include the existing carrier DTS first and the P3701-0008 module DTSI second:

```dts
/dts-v1/;
#include "<carrier-p3701-0000>.dts"
#include "tegra234-p3701-0008.dtsi"
/ {
    model = "Jetson AGX Orin Industrial on <carrier>";
    compatible = "nvidia,<carrier>+p3701-0008", "nvidia,p3701-0008", "nvidia,tegra234";
};
```

Create separate normal and GMSL variants when the carrier already has separate base DTS files. Register every new DTB in `nv-platform/Makefile`.

Never point SKU 0008 at a `p3701-0005` DTB. P3701-0008 is INT-fused hardware and must include `tegra234-p3701-0008.dtsi`.

## Build and stage DTBs

Use the BSP's canonical DT build flow. For an already prepared R36.x source tree:

```bash
export ARCH=arm64
export CROSS_COMPILE=<toolchain-prefix-with-trailing-dash>
make -C source \
  KERNEL_HEADERS="$PWD/source/kernel_out/kernel/kernel-jammy-src" \
  KERNEL_OUTPUT="$PWD/source/kernel_out/kernel/kernel-jammy-src" \
  nvidia-dtbs
```

Copy the resulting DTBs from `source/kernel-devicetree/generic-dts/dtbs/` to `kernel/dtb/`. Validate `model` and `compatible` with `fdtget` before flashing.

On R39/JetPack 7, the same target commonly writes DTBs under `source/kernel_out/build/nvidia-public/devicetree/generic-dtbs/`; use the actual path printed by the build and stage the carrier DTB into `kernel/dtb/`.

## Flash NVMe safely

For an external NVMe rootfs, use the Industrial QSPI-only layout:

```bash
sudo BOARDID=3701 BOARDSKU=0008 FAB=<detected-fab> BOARDREV=<detected-rev> \
CHIP_SKU="00:00:00:90" \
./tools/kernel_flash/l4t_initrd_flash.sh \
  --external-device nvme0n1p1 \
  -c tools/kernel_flash/flash_l4t_t234_nvme.xml \
  -p "-c bootloader/generic/cfg/flash_t234_qspi_industrial.xml" \
  --showlogs --network usb0 \
  <carrier-board-name> external
```

Do not use `flash_t234_qspi.xml` for P3701-0008. The generic layout lacks `A_fsi-fw`, `B_fsi-fw`, and `bad-page` partitions.

Before writing hardware, add `--no-flash`. Confirm the generated `tegraflash.py` command contains `fsi_fw fsi-lk.bin`, the TE992M BPMP firmware, the 0008 BPMP DTB, and the carrier's 0008 kernel DTB.

## Diagnose failures

- `Unrecognized module SKU 0008`: fix the common-function call order and add the 0008 branch.
- `RCM-boot started`, followed by endless `Waiting for target to boot-up`: confirm FSI firmware and the Industrial QSPI XML; capture the target serial console.
- Target remains `0955:7023 APX`: the device did not reach the initrd USB gadget/network stage.
- `try getting custinfo fail. Moving on`: treat as non-fatal when EEPROM identification follows successfully.
- Failure while writing ESP after SSH becomes ready: investigate USB/NFS/network stability, not SKU selection.

Capture serial at `115200 8N1` from before starting flash. Use MB1/MB2/UEFI output to identify boot-stage failures that host logs cannot expose.

## Validate before committing

Require all of the following:

1. `--no-flash` image generation succeeds.
2. RCM blob includes `fsi_fw fsi-lk.bin`.
3. Device reaches initrd SSH over USB.
4. QSPI and NVMe flashing complete.
5. Target boots and reports `p3701-0008` compatibility.
6. Ethernet, NVMe, USB, fan, RTC, GPIO, display, and carrier-specific camera/GMSL functions pass.

Keep changes uncommitted during bring-up if requested, but report untracked DTS files and modified Makefiles because `git clean` or source resync can remove them.
