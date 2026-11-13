# P3701-0008 adaptation reference

## Module mapping

| Field | AGX Orin Industrial |
|---|---|
| Board ID | `3701` |
| Board SKU | `0008` |
| Chip SKU | `00:00:00:90` |
| RAMCODE | `4` |
| BPMP firmware family | `TE992M-A1` |
| Module DTSI | `tegra234-p3701-0008.dtsi` |

Do not confuse P3701-0008 with P3701-0005. Both can be 64 GB modules, but they use different fuse, firmware, memory, PMIC, and device-tree data.

## Required Industrial resources

Verify these files exist under `Linux_for_Tegra`:

```text
bootloader/fsi-lk.bin
bootloader/generic/cfg/flash_t234_qspi_industrial.xml
bootloader/generic/cfg/flash_t234_qspi_sdmmc_industrial.xml
bootloader/generic/BCT/tegra234-p3701-0008-sdram-l4t.dts
bootloader/generic/BCT/tegra234-p3701-0008-wb0sdram-l4t.dts
bootloader/generic/BCT/tegra234-mb1-bct-pmic-p3701-0008.dts
bootloader/generic/BCT/tegra234-mb1-bct-misc-p3701-0008-flash.dts
bootloader/generic/BCT/tegra234-mb1-bct-misc-p3701-0008.dts
bootloader/generic/BCT/tegra234-mb2-bct-misc-p3701-0008.dts
```

R39/JetPack 7 may expose these selections through `set_p3701_0008_industrial_args` in the NVIDIA P3737/P3701 config. Reuse that helper instead of duplicating its variables in every carrier config. A carrier without CVB EEPROM may still override the helper's MB2 BCT with its corresponding `p3701-0008-*-no-cvb-eeprom.dts` file.

The BPMP DTB filename includes the carrier ID. For a P3737-derived J501 carrier, use `tegra234-bpmp-3701-0008-3737-0000.dtb` unless the carrier has a separately built BPMP DTB.

## Carrier/module ownership boundary

Preserve from the carrier BSP:

- pinmux and pad-voltage configuration;
- UPHY lane assignment and ODMDATA;
- Ethernet PHY, PCIe, NVMe, USB, RTC, fan, GPIO, CAN, and audio nodes;
- camera and GMSL topology;
- carrier overlays.

Replace for P3701-0008:

- SDRAM and WB0 SDRAM BCT;
- PMIC BCT;
- MB1 flash and cold-boot misc BCT;
- MB2 misc BCT;
- BPMP DTB selection;
- module DTSI and compatible strings;
- FSI firmware and bad-page partition support;
- QSPI partition layout.

## Expected RCM command evidence

The generated `tegraflash.py` command should contain entries equivalent to:

```text
fsi_fw fsi-lk.bin
bpmp_fw bpmp_t234-TE992M-A1_prod_sigheader.bin.encrypt
bpmp_fw_dtb tegra234-bpmp-3701-0008-<carrier>_with_odm_sigheader.dtb.encrypt
kernel_dtb <carrier-p3701-0008>.dtb
```

If FSI is absent, stop before retrying hardware flash.

## Runtime validation

Confirm the booted DTB reports both:

```text
nvidia,p3701-0008
nvidia,tegra234
```

Then validate carrier peripherals rather than treating a successful login as complete BSP qualification.
