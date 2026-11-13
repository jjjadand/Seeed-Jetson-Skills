#!/usr/bin/env python3
"""Install a verified job with image/metadata backups; never starts flashing."""
import argparse
import os
import shutil
from pathlib import Path

from common import app_row, discover, load, require, save, sha1


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def stage(source, destination, info):
    with source.open('rb') as src, destination.open('xb') as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())
    destination.chmod(info.st_mode & 0o777)
    if (destination.stat().st_uid, destination.stat().st_gid) != (info.st_uid, info.st_gid):
        os.chown(destination, info.st_uid, info.st_gid)


def install(work, check_only=False):
    work = Path(work).resolve()
    report = load(work / 'report.json')
    mfi, external, image, expected = discover(report['mfi_dir'])
    replacement, backup = Path(report['replacement_image']), Path(report['backup_image'])
    require(image.name == report['image_name'], 'Prepared job names another APP')
    require(expected == report['original_sha1'], 'Target APP metadata changed')
    require(replacement.stat().st_dev == image.stat().st_dev == backup.parent.stat().st_dev,
            'Prepare the job on the same filesystem as the MFI for atomic replacement')
    require(not backup.exists(), 'Backup already exists; inspect the previous transaction before retrying')
    names = ['flash.idx', image.name + '.sha1sum']
    for name in names:
        require((external / name).read_bytes() == (work / 'original' / name).read_bytes(), f'Metadata changed: {name}')
    require(sha1(image) == expected, 'Original APP SHA1 mismatch')
    require(sha1(replacement) == report['replacement_sha1'], 'Replacement APP SHA1 mismatch')
    _, row = app_row((work / 'flash.idx').read_text(), image.name)
    require(row[-1].strip() == report['replacement_sha1'], 'Prepared index SHA1 mismatch')
    require((work / (image.name + '.sha1sum')).read_text().split()[0] == report['replacement_sha1'],
            'Prepared sidecar SHA1 mismatch')
    if check_only:
        print('PASS installation preflight; no changes made', flush=True)
        return
    attributes = {name: (external / name).stat() for name in names}
    temporary = {name: external / (name + '.login-branding-new') for name in names}
    require(all(not path.exists() for path in temporary.values()), 'Stale staged metadata requires inspection')
    changed = False
    try:
        for name in names:
            stage(work / name, temporary[name], attributes[name])
        os.link(image, backup)
        sync_directory(backup.parent)
        require(image.stat().st_ino == backup.stat().st_ino, 'Original backup link differs')
        replacement.chmod(report['original_mode'])
        if (replacement.stat().st_uid, replacement.stat().st_gid) != (report['original_uid'], report['original_gid']):
            os.chown(replacement, report['original_uid'], report['original_gid'])
        save(work / 'transaction.json', dict(phase='backup-ready', backup=str(backup)))
        os.replace(replacement, image)
        changed = True
        for name in names:
            os.replace(temporary[name], external / name)
        sync_directory(external)
        require(sha1(image) == report['replacement_sha1'], 'Installed image SHA1 mismatch')
        require(backup.is_file() and sha1(backup) == expected, 'Original APP backup unavailable or changed')
        require(backup.stat().st_ino != image.stat().st_ino, 'Installed image aliases its backup')
        _, row = app_row((external / 'flash.idx').read_text(), image.name)
        require(row[-1].strip() == report['replacement_sha1'], 'Installed index mismatch')
        require((external / (image.name + '.sha1sum')).read_text().split()[0] == report['replacement_sha1'],
                'Installed sidecar mismatch')
        save(work / 'installed.json', dict(report, installed=True, backup_verified=True, hardware_flashed=False))
        save(work / 'transaction.json', dict(phase='complete', backup=str(backup)))
        print('PASS installed APP and both checksums; original backup verified:', backup, flush=True)
    except BaseException:
        if changed:
            restore = external / (image.name + '.login-branding-rollback')
            require(not restore.exists(), 'Stale rollback path requires manual recovery')
            os.link(backup, restore)
            os.replace(restore, image)
            for name in names:
                temporary[name].unlink(missing_ok=True)
                stage(work / 'original' / name, temporary[name], attributes[name])
                os.replace(temporary[name], external / name)
            sync_directory(external)
        for path in temporary.values():
            path.unlink(missing_ok=True)
        save(work / 'transaction.json', dict(phase='failed-restored' if changed else 'failed-before-replacement', backup=str(backup)))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    install(args.work, args.check)
