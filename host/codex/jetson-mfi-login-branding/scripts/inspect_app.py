#!/usr/bin/env python3
"""Read external Zstandard APP tar; extract GDM inputs without touching the MFI."""
import argparse
import collections
import hashlib
import tarfile
import time
from pathlib import Path

import zstandard
from common import discover, normalize, require, save

WANTED = {
    'etc/passwd', 'etc/group', 'etc/os-release', 'usr/lib/os-release',
    'usr/share/dconf/profile/gdm', 'var/lib/gdm3/greeter-dconf-defaults',
    'var/lib/gdm3/.config/dconf/user', 'usr/share/gdm/generate-config',
    'lib/systemd/system/gdm.service', 'lib/systemd/system/gdm3.service',
    'usr/lib/systemd/system/gdm.service', 'usr/lib/systemd/system/gdm3.service',
    'etc/systemd/system/display-manager.service',
    'usr/lib/gnome-shell/libshell-14.so',
    'usr/share/glib-2.0/schemas/org.gnome.login-screen.gschema.xml',
}
PREFIXES = ('etc/gdm3/', 'usr/share/gdm/dconf/', 'etc/dconf/',
            'etc/systemd/system/gdm.service.d/', 'etc/systemd/system/gdm3.service.d/',
            'usr/local/sbin/', 'usr/share/pixmaps/')


class HashedReader:
    def __init__(self, raw):
        self.raw, self.digest = raw, hashlib.sha1()

    def read(self, size=-1):
        data = self.raw.read(size)
        self.digest.update(data)
        return data


def inspect(mfi, output):
    mfi, external, source, expected = discover(mfi)
    info = source.stat()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    counts, members = collections.Counter(), {}
    last = time.monotonic()
    print('Reading APP tar and verifying source SHA1...', flush=True)
    with source.open('rb') as raw:
        hashed = HashedReader(raw)
        with zstandard.ZstdDecompressor().stream_reader(hashed) as decoded:
            with tarfile.open(fileobj=decoded, mode='r|', bufsize=4 * 1024 * 1024) as archive:
                for member in archive:
                    name = normalize(member.name)
                    counts[name] += 1
                    if name in WANTED or name.startswith(PREFIXES):
                        meta = dict(name=member.name, offset=member.offset, offset_data=member.offset_data,
                                    size=member.size, type=member.type.decode(), mode=member.mode,
                                    uid=member.uid, gid=member.gid, pax=member.pax_headers,
                                    linkname=member.linkname)
                        if member.isreg():
                            require(member.size <= 64 * 1024 * 1024, f'Inspect large file manually: {name}')
                            data = archive.extractfile(member).read()
                            path = output / name
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(data)
                            meta['sha256'] = hashlib.sha256(data).hexdigest()
                        members[name] = meta
                    if time.monotonic() - last > 20:
                        print(f'Inspected {member.offset_data / 1e9:.1f} GB', flush=True)
                        last = time.monotonic()
                end = archive.offset
            while data := decoded.read(8 * 1024 * 1024):
                require(not any(data), 'Nonzero data after tar end; inspect concatenated archive manually')
        require(not raw.read(1), 'Unread compressed bytes')
    require(hashed.digest.hexdigest() == expected, 'Source APP SHA1 mismatch')
    require(source.stat().st_size == info.st_size and source.stat().st_mtime_ns == info.st_mtime_ns,
            'Source APP changed during inspection')
    result = dict(mfi_dir=str(mfi), source=str(source), source_sha1=expected,
                  source_size=info.st_size, tar_end=end, entry_count=sum(counts.values()),
                  members=members, duplicates={n: c for n, c in counts.items() if c > 1})
    save(output / 'report.json', result)
    print(f'PASS APP SHA1 {expected}; {len(members)} GDM/support members selected', flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mfi_dir', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inspect(args.mfi_dir, args.output)
