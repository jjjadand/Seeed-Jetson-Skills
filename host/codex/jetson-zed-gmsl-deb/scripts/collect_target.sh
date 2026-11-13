#!/usr/bin/env bash
# Run ON the Jetson. No SSH, hardware scans, module loading, or service changes.
set -euo pipefail
if [[ $# -ne 2 || $1 != --output || -z $2 ]]; then
    printf 'Usage: bash collect_target.sh --output NEW_EVIDENCE_DIRECTORY\n' >&2
    exit 2
fi
capture_dir=$2
if [[ -e $capture_dir ]]; then
    printf 'Use a new evidence directory; existing path: %s\n' "$capture_dir" >&2
    exit 2
fi
mkdir -p "$capture_dir"
capture_dir=$(realpath "$capture_dir")
capture() {
    local name=$1
    shift
    local status=0
    "$@" > "$capture_dir/$name.log" 2>&1 || status=$?
    printf '%s\t%s\n' "$name" "$status" >> "$capture_dir/command-status.tsv"
}
capture identity bash -c 'date -Is; uname -a; cat /etc/nv_tegra_release; cat /proc/sys/kernel/random/boot_id; cat /proc/uptime; cat /proc/cmdline'
capture board bash -c 'for f in model compatible; do tr "\0" "\n" < /proc/device-tree/$f; done'
capture packages bash -c 'dpkg-query -W "nvidia-l4t-*" "stereolabs*" 2>/dev/null'
capture boot bash -c 'cat /boot/extlinux/extlinux.conf; ls -l /boot/dtb /boot/stereolabs; cat /boot/stereolabs/utils/zlconfig /boot/stereolabs/utils/carrier'
capture services systemctl status --no-pager -l driver_zed_loader zed_x_daemon IMU_Daemon nvargus-daemon
capture service-journal journalctl -b --no-pager -u driver_zed_loader -u zed_x_daemon -u IMU_Daemon -u nvargus-daemon -n 500
capture modules lsmod
capture clients ps -eo pid,ppid,stat,args
capture video bash -c 'ls -l /dev/video* /dev/media* /dev/v4l-subdev*'
if command -v i2cdetect >/dev/null; then capture i2c-adapters i2cdetect -l; fi
if [[ $EUID -eq 0 ]]; then
    capture kernel dmesg
elif sudo -n true 2>/dev/null; then
    capture kernel sudo -n dmesg
else
    capture kernel dmesg
fi
if [[ -r /sys/firmware/fdt ]]; then cp /sys/firmware/fdt "$capture_dir/live.dtb"; fi
for name in tegra_camera sl_max96712 sl_max9295 sl_zedx bmi088 bmi_spsc; do
    capture "modinfo-$name" modinfo "$name"
    if module_path=$(modinfo -n "$name" 2>/dev/null) && [[ -f $module_path ]]; then
        capture "sha256-$name" sha256sum "$module_path"
        capture "exports-$name" modprobe --show-exports "$module_path"
        capture "imports-$name" modprobe --show-modversions "$module_path"
    fi
done
printf 'Saved evidence to %s. See command-status.tsv for unavailable/privileged checks.\n' "$capture_dir"
