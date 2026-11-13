#!/bin/bash
# Apply only the reviewed text-file fixes; never starts a flash operation.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
bundle_dir="${script_dir}/../assets/repair"
check_only=0
if [ "${1:-}" = "--check" ]; then
	check_only=1
	shift
fi
if [ "$#" != 1 ]; then
    printf 'Usage: bash %s [--check] /absolute/path/to/mfi_recomputer-orin-super-j401\n' "${BASH_SOURCE[0]}" >&2
    exit 2
fi
target_dir=$1
target_dir=$(cd -- "${target_dir}" && pwd)
files=(
	recomputer-orin-super-j401.conf
	tools/kernel_flash/l4t_initrd_flash.sh
	tools/kernel_flash/l4t_flash_from_kernel.sh
	tools/kernel_flash/images/l4t_flash_from_kernel.sh
)

for file in p3767.conf.common bootloader/flashcmd.txt tools/kernel_flash/initrdflashparam.txt; do
	if [ ! -f "${target_dir}/${file}" ]; then
		printf 'Incomplete MFI package: missing %s\n' "${target_dir}/${file}" >&2
		exit 1
	fi
done
saved_board=$(awk 'NF >= 2 {print $(NF-1); exit}' "${target_dir}/tools/kernel_flash/initrdflashparam.txt")
if [ "${saved_board}" != recomputer-orin-super-j401 ]; then
	printf 'This repair is for recomputer-orin-super-j401; saved board is %s\n' "${saved_board}" >&2
	exit 1
fi

for file in "${files[@]}"; do
	bash -n "${bundle_dir}/patched/${file}"
	if ! cmp -s "${target_dir}/${file}" "${bundle_dir}/original/${file}" &&
	   ! cmp -s "${target_dir}/${file}" "${bundle_dir}/patched/${file}"; then
		printf 'Refusing to replace a file that differs from the reviewed versions: %s\n' "${target_dir}/${file}" >&2
		exit 1
	fi
done
cmp "${bundle_dir}/patched/tools/kernel_flash/l4t_flash_from_kernel.sh" \
	"${bundle_dir}/patched/tools/kernel_flash/images/l4t_flash_from_kernel.sh"
if [ "${check_only}" = 1 ]; then
	printf 'Preflight passed for %s (no files changed).\n' "${target_dir}"
	exit 0
fi
if [ "$(id -u)" != 0 ]; then
	printf 'The MFI files are owned by root. Run: sudo bash %q %q\n' "${BASH_SOURCE[0]}" "${target_dir}" >&2
	exit 1
fi

backup_dir=$(mktemp -d "${target_dir}/.mfi-fix-backup-XXXXXX")
for file in "${files[@]}"; do
	(cd -- "${target_dir}" && cp -a --parents -- "${file}" "${backup_dir}/")
done
rollback_on_error()
{
	local status=$?
	trap - ERR
	printf 'Installation failed; restoring originals from %s\n' "${backup_dir}" >&2
	for file in "${files[@]}"; do
		cp -a -- "${backup_dir}/${file}" "${target_dir}/${file}"
	done
	exit "${status}"
}
trap rollback_on_error ERR

for file in "${files[@]}"; do
	mode=0755
	if [[ "${file}" == *.conf ]]; then
		mode=0644
	fi
	install -m "${mode}" -- "${bundle_dir}/patched/${file}" "${target_dir}/${file}.mfi-new"
	mv -f -- "${target_dir}/${file}.mfi-new" "${target_dir}/${file}"
	cmp "${bundle_dir}/patched/${file}" "${target_dir}/${file}"
done
trap - ERR
printf 'Applied 4 file fixes to %s\nBackup: %s\nNo device was flashed.\n' "${target_dir}" "${backup_dir}"
