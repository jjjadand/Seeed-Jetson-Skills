#!/usr/bin/env python3
"""Small isolated APP fixtures exercise real tar, dconf, updates and rollback."""
import io
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

import zstandard
from common import load, save, sha1
from inspect_app import inspect
from build_payload import build, parse_settings, settings
from prepare_app import prepare
from install_prepared import install


def fixture(root):
    external = root / 'mfi/tools/kernel_flash/images/external'
    external.mkdir(parents=True)
    source = external / 'sample-app.img'
    keydir = root / 'cached-keys'
    keydir.mkdir()
    (keydir / '00-settings').write_text("[org/gnome/desktop/interface]\nclock-show-seconds=true\n")
    database = root / 'cached-db'
    subprocess.run(['dconf', 'compile', str(database), str(keydir)], check=True)
    content = {
        'etc/gdm3/greeter.dconf-defaults': b'# Debian defaults\n',
        'usr/share/gdm/dconf/00-settings': b'[org/gnome/desktop/interface]\nclock-show-seconds=true\n',
        'usr/share/gdm/dconf/locks/00-settings': b'/org/gnome/desktop/interface/clock-show-seconds\n',
        'var/lib/gdm3/greeter-dconf-defaults': database.read_bytes(),
        'usr/share/dconf/profile/gdm': b'user-db:user\nfile-db:/var/lib/gdm3/greeter-dconf-defaults\n',
        'usr/share/glib-2.0/schemas/org.gnome.login-screen.gschema.xml':
            b'<schemalist><schema><key name="logo"/><key name="fallback-logo"/><key name="banner-message-enable"/></schema></schemalist>',
        'usr/lib/systemd/system/gdm.service': b'[Service]\nExecStartPre=/usr/share/gdm/generate-config\nExecStart=/usr/sbin/gdm3\n',
        'etc/systemd/system/gdm.service.d/override.conf': b'[Service]\nExecStartPre=\n',
        'etc/untouched': b'original data with xattr and hardlink\n',
    }
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.PAX_FORMAT) as archive:
        for name, data in content.items():
            entry = tarfile.TarInfo('./' + name)
            entry.size, entry.mode, entry.mtime = len(data), 0o644, 1234567890
            entry.uid, entry.gid = (321, 654) if name.startswith('var/lib/gdm3/') else (0, 0)
            if name == 'etc/untouched':
                entry.pax_headers = {'SCHILY.xattr.user.branding-test': 'keep-me'}
            archive.addfile(entry, io.BytesIO(data))
        entry = tarfile.TarInfo('./usr/share/gdm/dconf/90-debian-settings')
        entry.type, entry.linkname = tarfile.SYMTYPE, '/etc/gdm3/greeter.dconf-defaults'
        archive.addfile(entry)
        entry = tarfile.TarInfo('./etc/untouched-link')
        entry.type, entry.linkname = tarfile.LNKTYPE, './etc/untouched'
        archive.addfile(entry)
    source.write_bytes(zstandard.ZstdCompressor(write_checksum=True).compress(stream.getvalue()))
    checksum = sha1(source)
    (external / 'flash.cfg').write_text('APP_ext=sample-app.img\nexternal_device=sda1\n')
    (external / 'flash.idx').write_text(f'2, 9:0:APP,0,85899345920,sample-app.img,85899345920,fixed-<reserved>-1,{checksum}\n')
    (external / 'sample-app.img.sha1sum').write_text(f'{checksum}  sample-app.img\n')
    return external.parent.parent.parent.parent, source, content


def read_members(image):
    members, bodies = {}, {}
    with image.open('rb') as raw, zstandard.ZstdDecompressor().stream_reader(raw) as decoded:
        with tarfile.open(fileobj=decoded, mode='r|') as archive:
            for member in archive:
                name = member.name.removeprefix('./')
                if name in members:
                    raise AssertionError('Duplicate path: ' + name)
                members[name] = member
                if member.isreg():
                    bodies[name] = archive.extractfile(member).read()
    return members, bodies


def expect_error(function, phrase):
    try:
        function()
    except ValueError as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError('Expected rejection: ' + phrase)


def main():
    with tempfile.TemporaryDirectory(prefix='jetson-login-test-') as temporary:
        root = Path(temporary)
        mfi, source, content = fixture(root)
        original = sha1(source)
        external = source.parent
        index = (external / 'flash.idx').read_bytes()
        inspection, payload, job = root / 'inspection', root / 'payload', root / 'job'
        inspect(mfi, inspection)
        build(inspection, payload, 'Jetson-Test')
        expect_error(lambda: build(inspection, root / 'multiline', 'first\nsecond'), 'one visible line')
        prepare(inspection, payload, job)
        assert sha1(source) == original and (external / 'flash.idx').read_bytes() == index
        install(job, check_only=True)
        assert sha1(source) == original and not (job / 'original/sample-app.img').exists()
        install(job)
        installed = load(job / 'installed.json')
        assert sha1(source) == installed['replacement_sha1']
        backup = job / 'original/sample-app.img'
        assert sha1(backup) == original and backup.stat().st_ino != source.stat().st_ino
        members, bodies = read_members(source)
        assert bodies['etc/untouched'] == content['etc/untouched']
        assert members['etc/untouched'].pax_headers['SCHILY.xattr.user.branding-test'] == 'keep-me'
        assert members['etc/untouched-link'].islnk()
        cached = members['var/lib/gdm3/greeter-dconf-defaults']
        assert (cached.uid, cached.gid, cached.mode) == (321, 654, 0o644)
        assert members['usr/local/sbin/jetson-login-prepare-login'].mode == 0o755
        assert (external / 'flash.cfg').read_text().endswith('external_device=sda1\n')
        assert (external / 'flash.idx').read_text().split(',')[:7] == index.decode().split(',')[:7]
        compiled = parse_settings(settings(job / 'verified/var/lib/gdm3/greeter-dconf-defaults'))
        assert compiled['org/gnome/desktop/interface/clock-show-seconds'] == 'true'
        print('PASS actual install preserves content, PAX xattr, hardlink, GDM ownership, partition geometry and sda config')

        inspect(mfi, root / 'inspection2')
        build(root / 'inspection2', root / 'payload2', 'Jetson-Changed')
        prepare(root / 'inspection2', root / 'payload2', root / 'job2')
        updated_members, updated_bodies = read_members(root / 'job2/sample-app.img')
        assert len(updated_members) == len(members)
        assert updated_bodies['usr/share/pixmaps/jetson-login-login.png'] != bodies['usr/share/pixmaps/jetson-login-login.png']
        before = sha1(source)
        second_index = (external / 'flash.idx').read_bytes()
        original_replace = os.replace
        failures = []

        def fail_metadata_once(src, dst):
            if str(src).endswith('flash.idx.login-branding-new') and not failures:
                failures.append(True)
                raise OSError('injected metadata installation failure')
            return original_replace(src, dst)

        try:
            with patch('install_prepared.os.replace', side_effect=fail_metadata_once):
                install(root / 'job2')
        except OSError as error:
            assert str(error) == 'injected metadata installation failure'
        else:
            raise AssertionError('Injected failure did not propagate')
        assert sha1(source) == before and (external / 'flash.idx').read_bytes() == second_index
        assert load(root / 'job2/transaction.json')['phase'] == 'failed-restored'
        changed_members, changed_bodies = read_members(root / 'job2/original/sample-app.img')
        assert len(changed_members) == len(members)
        assert changed_bodies['usr/share/pixmaps/jetson-login-login.png'] == bodies['usr/share/pixmaps/jetson-login-login.png']
        print('PASS tag update reuses existing paths without duplicates; interrupted installation restores image and checksums')

        report = load(inspection / 'report.json')
        report['source_sha1'] = '0' * 40
        save(inspection / 'report.json', report)
        expect_error(lambda: prepare(inspection, payload, root / 'stale-job'), 'Inspection belongs to another APP')
        assert sha1(source) == before
        print('PASS stale inspection rejected without modifying the MFI')
    print('PASS all fixture checks; no real MFI or block device was modified')


if __name__ == '__main__':
    main()
