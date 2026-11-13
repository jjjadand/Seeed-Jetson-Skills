#!/usr/bin/env python3
"""Prepare and verify a replacement APP; preserve every unmodified tar byte."""
import argparse
import hashlib
import io
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

import zstandard
from common import app_row, discover, load, normalize, require, save, sha1
from inspect_app import HashedReader


def prepare(inspection, payload, output):
    inspection, payload, output = (Path(p).resolve() for p in (inspection, payload, output))
    report = load(inspection / 'report.json')
    mfi, external, source, expected = discover(report['mfi_dir'])
    require(str(source) == report['source'] and expected == report['source_sha1'], 'Inspection belongs to another APP')
    info = source.stat()
    require(info.st_size == report['source_size'], 'Source size changed since inspection')
    require(shutil.disk_usage(output.parent).free > info.st_size + 512 * 1024 * 1024,
            'Need space for a replacement image plus margin')
    manifest = load(payload / 'manifest.json')
    for name, meta in manifest.items():
        require(normalize(name) == name, f'Invalid manifest path: {name}')
        require(hashlib.sha256((payload / 'files' / name).read_bytes()).hexdigest() == meta['sha256'],
                f'Payload changed: {name}')
    members = report['members']
    modified = sorted((n for n in manifest if n in members), key=lambda n: members[n]['offset_data'])
    for name in modified:
        meta = members[name]
        require(name not in report['duplicates'], f'Duplicate member requires manual adaptation: {name}')
        require(meta['type'] == '0' and 'size' not in meta['pax'],
                f'Expected regular file without PAX size: {name}')
        require(meta['mode'] == manifest[name]['mode'], f'Existing mode differs; adapt explicitly: {name}')
    output.mkdir(exist_ok=False)
    originals = output / 'original'
    originals.mkdir()
    for name in ('flash.idx', source.name + '.sha1sum'):
        shutil.copy2(external / name, originals / name)
    destination = output / source.name
    source_position = 0
    regions, unchanged = [], hashlib.sha256()
    last = time.monotonic()
    print('Preparing replacement APP; target package remains unchanged...', flush=True)
    with source.open('rb') as raw, destination.open('xb') as target:
        hashed = HashedReader(raw)
        with zstandard.ZstdDecompressor().stream_reader(hashed) as decoded, \
                zstandard.ZstdCompressor(level=3, threads=4, write_checksum=True).stream_writer(target, closefd=False) as encoded:
            def read_exact(size):
                nonlocal source_position
                data = decoded.read(size)
                require(len(data) == size, 'Truncated APP')
                source_position += size
                return data

            def copy_to(position):
                nonlocal last
                size = position - source_position
                require(size >= 0, 'Overlapping tar records')
                if size:
                    regions.append(dict(kind='unchanged', size=size))
                while source_position < position:
                    data = read_exact(min(8 * 1024 * 1024, position - source_position))
                    encoded.write(data)
                    unchanged.update(data)
                    if time.monotonic() - last > 20:
                        print(f'Processed {source_position / 1e9:.1f} GB', flush=True)
                        last = time.monotonic()

            for name in modified:
                meta = members[name]
                copy_to(meta['offset_data'] - 512)
                header = bytearray(read_exact(512))
                parsed = tarfile.TarInfo.frombuf(bytes(header), 'utf-8', 'surrogateescape')
                require(normalize(parsed.name) == name and parsed.size == meta['size'], 'Tar header differs from inspection')
                old = read_exact((meta['size'] + 511) // 512 * 512)
                require(hashlib.sha256(old[:meta['size']]).hexdigest() == meta['sha256'], f'Original content changed: {name}')
                body = (payload / 'files' / name).read_bytes()
                header[124:136] = f'{len(body):011o}\0'.encode()
                header[148:156] = b' ' * 8
                header[148:156] = f'{sum(header):06o}\0 '.encode()
                segment = bytes(header) + body + bytes((-len(body)) % 512)
                encoded.write(segment)
                regions.append(dict(kind='replacement', path=name, size=len(segment),
                                    sha256=hashlib.sha256(segment).hexdigest()))
            copy_to(report['tar_end'])
            while data := decoded.read(8 * 1024 * 1024):
                require(not any(data), 'Nonzero data after tar end')
            tail = io.BytesIO()
            with tarfile.open(fileobj=tail, mode='w', format=tarfile.PAX_FORMAT) as extra:
                for name, meta in manifest.items():
                    if name in modified:
                        continue
                    body = (payload / 'files' / name).read_bytes()
                    member = tarfile.TarInfo('./' + name)
                    member.uid = member.gid = 0
                    member.uname = member.gname = 'root'
                    member.mode = meta['mode']
                    member.mtime = int(time.time())
                    member.size = len(body)
                    extra.addfile(member, io.BytesIO(body))
            encoded.write(tail.getvalue())
        target.flush()
        os.fsync(target.fileno())
    require(hashed.digest.hexdigest() == expected, 'Source APP changed; discard this prepared job')
    print('Verifying GNU tar extraction and unchanged byte regions...', flush=True)
    extracted = output / 'verified'
    extracted.mkdir()
    names = [members[n]['name'] if n in members else './' + n for n in manifest]
    with tempfile_errors(output) as errors:
        process = subprocess.Popen(['tar', '-xpf', '-', '--no-same-owner', '--warning=no-unknown-keyword',
                                    '--xattrs', '--xattrs-include=*', '-C', str(extracted), *names],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
        checked = hashlib.sha256()
        try:
            with destination.open('rb') as raw, zstandard.ZstdDecompressor().stream_reader(raw) as decoded:
                for region in regions:
                    remaining, digest = region['size'], hashlib.sha256()
                    while remaining:
                        data = decoded.read(min(8 * 1024 * 1024, remaining))
                        require(data, 'Truncated replacement')
                        process.stdin.write(data)
                        (checked if region['kind'] == 'unchanged' else digest).update(data)
                        remaining -= len(data)
                    if region['kind'] == 'replacement':
                        require(digest.hexdigest() == region['sha256'], 'Replacement region differs')
                while data := decoded.read(8 * 1024 * 1024):
                    process.stdin.write(data)
            process.stdin.close()
            require(process.wait() == 0, 'GNU tar extraction failed; see tar-errors.log')
        except BaseException:
            process.kill()
            process.wait()
            raise
    require(checked.hexdigest() == unchanged.hexdigest(), 'Unmodified archive bytes changed')
    for name, meta in manifest.items():
        actual = extracted / name
        require(hashlib.sha256(actual.read_bytes()).hexdigest() == meta['sha256'], f'Extracted content differs: {name}')
        require(actual.stat().st_mode & 0o777 == meta['mode'], f'Extracted mode differs: {name}')
    checksum = sha1(destination)
    original_index = (originals / 'flash.idx').read_text()
    index, fields = app_row(original_index, source.name)
    fields[-1] = checksum
    lines = original_index.splitlines(keepends=True)
    lines[index] = ','.join(fields) + '\n'
    (output / 'flash.idx').write_text(''.join(lines))
    (output / (source.name + '.sha1sum')).write_text(f'{checksum}  {source.name}\n')
    result = dict(mfi_dir=str(mfi), image_name=source.name, replacement_image=str(destination),
                  backup_image=str(originals / source.name), original_sha1=expected,
                  replacement_sha1=checksum, original_mode=info.st_mode & 0o777,
                  original_uid=info.st_uid, original_gid=info.st_gid,
                  modified_members=modified, added_members=[n for n in manifest if n not in modified],
                  unchanged_regions_sha256=unchanged.hexdigest(), regions=regions,
                  validation='GNU tar extraction, unchanged regions, content/modes, complete zstd stream')
    save(output / 'report.json', result)
    print('PASS prepared APP SHA1', checksum, flush=True)
    return result


def tempfile_errors(output):
    return (output / 'tar-errors.log').open('w+b')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspection', type=Path, required=True)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.inspection, args.payload, args.output)
