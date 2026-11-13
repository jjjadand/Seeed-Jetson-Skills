#!/usr/bin/env bash
set -u

L4T_ROOT="${1:-$PWD}"
BOARD="${2:-}"
failures=0

if [ -z "${BOARD}" ]; then
    echo "Usage: $0 <Linux_for_Tegra> <board-name-without-.conf>" >&2
    exit 2
fi

CONFIG="${L4T_ROOT}/${BOARD}.conf"
CONFIG_CONTEXT="$(mktemp)"
trap 'rm -f "${CONFIG_CONTEXT}"' EXIT

collect_config_context() {
    local file="$1"
    local source_name

    if [ ! -s "${file}" ] || grep -Fqx "### ${file}" "${CONFIG_CONTEXT}"; then
        return
    fi

    printf '### %s\n' "${file}" >> "${CONFIG_CONTEXT}"
    cat "${file}" >> "${CONFIG_CONTEXT}"

    while IFS= read -r source_name; do
        collect_config_context "${L4T_ROOT}/${source_name}"
    done < <(sed -nE 's|^[[:space:]]*source[[:space:]]+"?\$\{LDK_DIR\}/([^";]+)"?;?.*$|\1|p' "${file}")
}

check_file() {
    if [ -s "$1" ]; then
        echo "PASS file $1"
    else
        echo "FAIL missing $1"
        failures=$((failures + 1))
    fi
}

check_pattern() {
    local pattern="$1"
    local file="$2"
    local label="$3"
    if grep -Eq "${pattern}" "${file}" 2>/dev/null; then
        echo "PASS ${label}"
    else
        echo "FAIL ${label}"
        failures=$((failures + 1))
    fi
}

check_file "${CONFIG}"
check_file "${L4T_ROOT}/bootloader/fsi-lk.bin"
check_file "${L4T_ROOT}/bootloader/generic/cfg/flash_t234_qspi_industrial.xml"

for name in \
    tegra234-p3701-0008-sdram-l4t.dts \
    tegra234-p3701-0008-wb0sdram-l4t.dts \
    tegra234-mb1-bct-pmic-p3701-0008.dts \
    tegra234-mb1-bct-misc-p3701-0008-flash.dts \
    tegra234-mb1-bct-misc-p3701-0008.dts \
    tegra234-mb2-bct-misc-p3701-0008.dts; do
    check_file "${L4T_ROOT}/bootloader/generic/BCT/${name}"
done

if [ -s "${CONFIG}" ]; then
    collect_config_context "${CONFIG}"
    check_pattern 'board_sku.*0008' "${CONFIG_CONTEXT}" "SKU 0008 branch"
    check_pattern 'FSIFWFILE=.*fsi-lk.bin' "${CONFIG_CONTEXT}" "FSI firmware selection"
    check_pattern 'BADPAGEFILE=.*badpage.bin' "${CONFIG_CONTEXT}" "bad-page support"
    check_pattern 'flash_t234_qspi_sdmmc_industrial.xml' "${CONFIG_CONTEXT}" "industrial default layout"
    check_pattern 'p3701-0008-sdram-l4t.dts' "${CONFIG_CONTEXT}" "industrial SDRAM BCT"
    check_pattern 'p3701-0008-wb0sdram-l4t.dts' "${CONFIG_CONTEXT}" "industrial WB0 BCT"
    check_pattern 'mb1-bct-pmic-p3701-0008.dts' "${CONFIG_CONTEXT}" "industrial PMIC BCT"
    check_pattern 'mb1-bct-misc-p3701-0008-flash.dts' "${CONFIG_CONTEXT}" "industrial MB1 flash BCT"
    check_pattern 'mb1-bct-misc-p3701-0008.dts' "${CONFIG_CONTEXT}" "industrial MB1 cold-boot BCT"
    check_pattern 'mb2-bct-misc-p3701-0008[^";]*\.dts' "${CONFIG_CONTEXT}" "industrial MB2 BCT"

    mapfile -t dtbs < <(grep -Eo 'tegra234-[A-Za-z0-9+_.-]*p3701-0008[A-Za-z0-9+_.-]*\.dtb' "${CONFIG}" | sort -u)
    if [ "${#dtbs[@]}" -eq 0 ]; then
        echo "FAIL no carrier P3701-0008 DTB referenced"
        failures=$((failures + 1))
    else
        for dtb in "${dtbs[@]}"; do
            check_file "${L4T_ROOT}/kernel/dtb/${dtb}"
            if command -v fdtget >/dev/null 2>&1 && [ -s "${L4T_ROOT}/kernel/dtb/${dtb}" ]; then
                compatible="$(fdtget -t s "${L4T_ROOT}/kernel/dtb/${dtb}" / compatible 2>/dev/null || true)"
                if printf '%s' "${compatible}" | grep -q 'nvidia,p3701-0008'; then
                    echo "PASS ${dtb} compatible includes nvidia,p3701-0008"
                else
                    echo "FAIL ${dtb} compatible does not include nvidia,p3701-0008"
                    failures=$((failures + 1))
                fi
            fi
        done
    fi
fi

if [ "${failures}" -ne 0 ]; then
    echo "RESULT: FAIL (${failures} issue(s))"
    exit 1
fi

echo "RESULT: PASS"
