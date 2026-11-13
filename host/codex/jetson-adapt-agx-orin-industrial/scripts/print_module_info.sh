#!/usr/bin/env bash
set -u

section() {
    printf '\n=== %s ===\n' "$1"
}

read_dt_property() {
    local label="$1"
    shift
    local path
    for path in "$@"; do
        if [ -r "${path}" ]; then
            printf '%-20s ' "${label}:"
            tr '\0' ' ' < "${path}"
            printf '\n'
            return 0
        fi
    done
    printf '%-20s unavailable\n' "${label}:"
}

section "Jetson Linux"
if [ -r /etc/nv_tegra_release ]; then
    head -1 /etc/nv_tegra_release
else
    echo "/etc/nv_tegra_release unavailable"
fi
uname -a

section "Module and Device Tree"
read_dt_property "Model" /proc/device-tree/model /sys/firmware/devicetree/base/model
read_dt_property "Compatible" /proc/device-tree/compatible /sys/firmware/devicetree/base/compatible
read_dt_property "Serial number" /proc/device-tree/serial-number /sys/firmware/devicetree/base/serial-number

if [ -r /etc/nv_boot_control.conf ]; then
    section "Boot Control Identity"
    awk '$1 ~ /^(TNSPEC|COMPATIBLE_SPEC|TEGRA_CHIPID|TEGRA_OTA_BOOT_DEVICE|TEGRA_OTA_GPT_DEVICE)$/ {print}' \
        /etc/nv_boot_control.conf
fi

section "Boot Slots"
if command -v nvbootctrl >/dev/null 2>&1; then
    nvbootctrl dump-slots-info 2>&1 || true
else
    echo "nvbootctrl unavailable"
fi

section "NVIDIA BSP Packages"
if command -v dpkg-query >/dev/null 2>&1; then
    dpkg-query -W -f='${Package}\t${Version}\n' \
        'nvidia-l4t-core' 'nvidia-l4t-kernel' 'nvidia-l4t-kernel-dtbs' \
        'nvidia-l4t-bootloader' 2>/dev/null || true
fi

section "Storage"
if command -v lsblk >/dev/null 2>&1; then
    lsblk -o NAME,MODEL,SERIAL,SIZE,TYPE,FSTYPE,MOUNTPOINTS
fi

section "Plugin Manager IDs"
found=0
for directory in /proc/device-tree/chosen/plugin-manager/ids /sys/firmware/devicetree/base/chosen/plugin-manager/ids; do
    if [ -d "${directory}" ]; then
        found=1
        find "${directory}" -maxdepth 1 -type f -printf '%f\n' 2>/dev/null | sort
    fi
done
if [ "${found}" -eq 0 ]; then
    echo "plugin-manager IDs unavailable on this release"
fi
