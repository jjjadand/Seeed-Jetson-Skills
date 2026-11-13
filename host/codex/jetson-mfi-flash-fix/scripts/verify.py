#!/usr/bin/env python3
"""Exercise MFI flash paths with mocked writes; never opens a real device."""

from pathlib import Path
import argparse
import shlex
import shutil
import subprocess
import tempfile


BUNDLE = Path(__file__).resolve().parent.parent / "assets" / "repair"
parser = argparse.ArgumentParser()
parser.add_argument("--target", type=Path, required=True, help="MFI directory to inspect; no real device is opened")
parser.add_argument("--installed", action="store_true")
args = parser.parse_args()
TARGET = args.target.resolve()
PATCHED = TARGET if args.installed else BUNDLE / "patched"
FLASH = Path("tools/kernel_flash/l4t_flash_from_kernel.sh")
WRAPPER = Path("tools/kernel_flash/l4t_initrd_flash.sh")
BOARD = Path("recomputer-orin-super-j401.conf")
passed = 0


def check(name, code, *, definitions=True, expected=None, argv=()):
    global passed
    if definitions:
        prefix = (PATCHED / FLASH).read_text().split("\ntrap cleanup EXIT\n", 1)[0]
        code = prefix + "\n" + LOG_STUBS + "\n" + code
    result = subprocess.run(["/bin/bash", "-c", "set -eo pipefail\n" + code, "mfi-test", *argv], text=True, capture_output=True)
    if result.returncode or (expected is not None and result.stdout != expected):
        raise AssertionError(f"{name}: exit={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr}")
    print(f"PASS {name}")
    passed += 1


LOG_STUBS = """
log_error() { printf '%s\\n' "$*" >&2; }
log_debug() { :; }
log_warning() { :; }
sync() { :; }
basename() { printf 'basename is unavailable\\n' >&2; return 127; }
"""

for name in (BOARD, WRAPPER, FLASH, Path("tools/kernel_flash/images/l4t_flash_from_kernel.sh")):
    subprocess.run(["/bin/bash", "-n", str(PATCHED / name)], check=True)
assert (PATCHED / FLASH).read_bytes() == (PATCHED / "tools/kernel_flash/images/l4t_flash_from_kernel.sh").read_bytes()
print("PASS shell syntax and identical runtime script copies")
passed += 1

cases = [
    ("nvme0n1", "2", "nvme0n1p2"),
    ("/dev/nvme0n1", "15", "/dev/nvme0n1p15"),
    ("nvme0n1p1", "2", "nvme0n1p2"),
    ("mmcblk0", "2", "mmcblk0p2"),
    ("/dev/mmcblk0p1", "2", "/dev/mmcblk0p2"),
    ("sda", "2", "sda2"),
    ("/dev/sda1", "2", "/dev/sda2"),
    ("loop0", "2", "loop0p2"),
    ("vda1", "2", "vda2"),
    ("xvdb3", "2", "xvdb2"),
    ("nvme0n1p1", "0", "nvme0n1"),
]
check("partition naming without basename", "\n".join(
    f'[[ "$(get_partition {shlex.quote(device)} {shlex.quote(number)})" == {shlex.quote(expected)} ]]'
    for device, number, expected in cases
))
check("reject empty device and invalid partition index", """
if get_partition '' 2; then exit 1; fi
if get_partition /dev/ 2; then exit 1; fi
if get_partition nvme0n1 invalid; then exit 1; fi
if get_partition nvme0n1 -1; then exit 1; fi
""")

with tempfile.TemporaryDirectory(prefix="mfi-verify-") as tmp:
    temp = Path(tmp)
    image_dir = temp / "external"
    image_dir.mkdir()
    (image_dir / "test.img").touch()
    setup = f"""
COMMON_IMAGES_DIR={shlex.quote(str(temp))}
VERIFY_WRITE=0
is_sparse_image() {{ return 1; }}
is_zstd_data() {{ return 0; }}
"""
    check("all NVMe backup partitions select p2 through p15", setup + """
write_zstd_image() { printf '%s\\n' "$1"; }
for part in {2..15}; do
    if ! flash_partition test.img "nvme0n1p${part}" 0 134217728 "fixed-<reserved>-${part}" unused /dev/nvme0n1 external; then
        exit 1
    fi
done
""", expected="".join(f"/dev/nvme0n1p{n}\n" for n in range(2, 16)))
    for fmt in ("zstd", "sparse"):
        check(f"{fmt} write failure reaches flash_partition caller", setup + f"""
is_sparse_image() {{ {'return 0' if fmt == 'sparse' else 'return 1'}; }}
write_{fmt}_image() {{ return 42; }}
if flash_partition test.img nvme0n1p2 0 134217728 'fixed-<reserved>-2' unused /dev/nvme0n1 external; then
    exit 1
fi
""")

    regular = temp / "regular-file"
    regular.write_text("unchanged")
    check("refuse missing device and regular file before discard or dd", f"""
host_mode=0
blkdiscard() {{ echo 'unexpected discard'; return 1; }}
dd() {{ echo 'unexpected dd'; return 1; }}
if erase_partition {shlex.quote(str(regular))}; then exit 1; fi
if erase_partition {shlex.quote(str(temp / 'missing'))}; then exit 1; fi
""", expected="")
    assert regular.read_text() == "unchanged"
    assert not (temp / "missing").exists()

    # Only the fake device below passes this test-only block-device predicate.
    block_stubs = """
[() {
    if [[ $# == 4 && "$1" == '!' && "$2" == '-b' && "$3" == /dev/mfi-test ]]; then return 1; fi
    builtin [ "$@"
}
blkdiscard() {
    if [[ "$1" == -h ]]; then printf '%s\\n' '-f, --force'; return 0; fi
    return 1
}
blockdev() { printf '%s\\n' 134217728; }
dd() { printf '%s\\n' "$*"; }
get_dev_name_on_target() { printf '%s\\n' mfi-test; }
run_commmand_on_target() { ( eval "$2" ); }
net=test
"""
    zero_command = "if=/dev/zero of=/dev/mfi-test bs=1M count=134217728 iflag=count_bytes status=progress oflag=direct\n"
    for label, mode in (("target", "host_mode=0; direct="), ("direct", "host_mode=1; direct=1"), ("remote", "host_mode=1; direct=")):
        check(f"{label} discard fallback zeros exactly the device size", block_stubs + "\n" + mode + "\nerase_partition /dev/mfi-test\n", expected=zero_command)
        check(f"{label} zero-fill failure is reported", block_stubs + "\n" + mode + """
dd() { return 7; }
if erase_partition /dev/mfi-test; then exit 1; fi
""")
    check("invalid device size prevents zero-fill", block_stubs + """
host_mode=0
blockdev() { printf '%s\\n' 0; }
if erase_partition /dev/mfi-test; then exit 1; fi
""", expected="")

    for failure in ("erase", "decompress", "write"):
        check(f"zstd {failure} failure is not masked by caller's if", f"""
erase_partition() {{ {'return 3' if failure == 'erase' else 'return 0'}; }}
zstd() {{ {'return 4' if failure == 'decompress' else 'printf data'}; }}
dd() {{ {'echo unexpected-dd; return 5' if failure == 'erase' else '/bin/cat >/dev/null; return ' + ('5' if failure == 'write' else '0')}; }}
if write_zstd_image /dev/mfi-test test.img; then exit 1; fi
""", expected="")
    check("sparse converter failure is reported", """
erase_partition() { return 0; }
nvsimg2img() { return 6; }
if write_sparse_image /dev/mfi-test test.img; then exit 1; fi
""", expected="nvsimg2img test.img /dev/mfi-test\n")

    fake = temp / "package"
    (fake / "bootloader").mkdir(parents=True)
    (fake / "tools/kernel_flash").mkdir(parents=True)
    shutil.copyfile(TARGET / "p3767.conf.common", fake / "p3767.conf.common")
    (fake / "bootloader/flashcmd.txt").touch()
    (fake / "tools/kernel_flash/initrdflashparam.txt").write_text("--network usb0 recomputer-orin-super-j401 internal\n")
    config = shlex.quote(str(PATCHED / BOARD))
    check("MFI board config supplies Tegra234 CHIPID", f"LDK_DIR={shlex.quote(str(fake))}; source {config}; [[ $CHIPID == 0x23 ]]", definitions=False)
    (fake / "p3768-0000-p3767-0000-a0.conf").write_text("CHIPID=0x99\n")
    check("full BSP board config takes precedence", f"LDK_DIR={shlex.quote(str(fake))}; source {config}; [[ $CHIPID == 0x99 ]]", definitions=False)
    (fake / "p3768-0000-p3767-0000-a0.conf").unlink()
    (fake / "bootloader/flashcmd.txt").unlink()
    check("incomplete package cannot use MFI config fallback", f"LDK_DIR={shlex.quote(str(fake))}; if source {config}; then exit 1; fi", definitions=False)

    wrapper = (PATCHED / WRAPPER).read_text().split("\n_UNIFIED_FLASH=", 1)[0]
    wrapper = wrapper.replace("trap cleanup EXIT\n", "")
    wrapper = wrapper.replace('L4T_INITRD_FLASH_DIR="$(dirname "$(readlink -e "${BASH_SOURCE[0]}")")"',
                              f"L4T_INITRD_FLASH_DIR={shlex.quote(str(TARGET / 'tools/kernel_flash'))}")
    check("exact massflash command resolves saved board before initial config load", wrapper + """
[[ $flash_only == 1 && $massflash_mode == 1 && $max_massflash == 1 ]]
[[ $network == usb0 && $showlogs == 1 && $target_board == recomputer-orin-super-j401 ]]
""", definitions=False, argv=("--flash-only", "--massflash", "1", "--network", "usb0", "--showlogs"))

    # Reproduce the reported failure using the unmodified script and mocked writes.
    original = (BUNDLE / "original" / FLASH).read_text().split("\ntrap cleanup EXIT\n", 1)[0]
    check("original script reproduces false success at /dev/2", original + "\n" + LOG_STUBS + "\n" + setup + """
write_zstd_image() { printf '%s\\n' "$1"; }
if ! flash_partition test.img nvme0n1p2 0 134217728 'fixed-<reserved>-2' unused /dev/nvme0n1 external; then exit 1; fi
""", definitions=False, expected="/dev/2\n")

print(f"{passed} checks passed; no real block device was opened or written.")
