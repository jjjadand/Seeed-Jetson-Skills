#!/usr/bin/env python3
"""Build a parameterized GDM logo, preserved defaults and compiled login database."""
import argparse
import hashlib
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from common import load, normalize, require, save

DATABASE = 'var/lib/gdm3/greeter-dconf-defaults'
KEYROOT = 'usr/share/gdm/dconf'
PREPARE = '''#!/bin/sh
set -eu
umask 022
database=/var/lib/gdm3/greeter-dconf-defaults
mkdir -p /var/lib/gdm3
if command -v dconf >/dev/null 2>&1; then
    if dconf compile "${database}.BRAND_ID-new" /usr/share/gdm/dconf; then
        chmod 0644 "${database}.BRAND_ID-new"
        if id gdm >/dev/null 2>&1; then
            chown "$(id -u gdm):$(id -g gdm)" "${database}.BRAND_ID-new" || true
        fi
        mv -f "${database}.BRAND_ID-new" "$database"
    else
        rm -f "${database}.BRAND_ID-new"
        # Preserve the already-compiled database embedded in the MFI image.
        test -r "$database"
    fi
fi
'''


def settings(database):
    with tempfile.TemporaryDirectory(prefix='jetson-login-dconf-') as temporary:
        profile = Path(temporary) / 'profile'
        profile.write_text('file-db:' + str(database.resolve()) + '\n')
        environment = dict(os.environ, DCONF_PROFILE=str(profile))
        return subprocess.check_output(['dconf', 'dump', '/'], env=environment, text=True)


def parse_settings(text):
    result, section = {}, ''
    for line in text.splitlines():
        if line.startswith('['):
            section = line[1:-1]
        elif '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            result[section + '/' + key] = value
    return result


def build(inspection, output, tag, identity='jetson-login', font_size=40, color='#22d3ee', font_path=None):
    inspection, output = Path(inspection).resolve(), Path(output).resolve()
    require(re.fullmatch(r'[a-z][a-z0-9-]{0,47}', identity), 'Use a short lowercase file identifier')
    require(tag and not any(ord(ch) < 32 or ord(ch) == 127 for ch in tag), 'Tag must be one visible line')
    require(12 <= font_size <= 144, 'Font size must be between 12 and 144')
    require(shutil.which('dconf'), 'Install/provide the host dconf CLI before building')
    report = load(inspection / 'report.json')
    members = report['members']
    require(DATABASE in members and members[DATABASE]['type'] == '0', 'Expected a regular compiled GDM database')
    require('var/lib/gdm3/.config/dconf/user' not in members,
            'Greeter has a user DB; inspect its logo overrides before adapting this helper')
    profile = (inspection / 'usr/share/dconf/profile/gdm').read_text()
    require('file-db:/' + DATABASE in profile, 'GDM reads another database; adapt paths before building')
    schema = ET.parse(inspection / 'usr/share/glib-2.0/schemas/org.gnome.login-screen.gschema.xml')
    keys_available = {key.attrib['name'] for key in schema.findall('.//key')}
    require({'logo', 'banner-message-enable'} <= keys_available, 'Target lacks required GDM logo settings')
    output.mkdir(parents=True, exist_ok=False)
    files = output / 'files'

    def write(name, data, mode=0o644):
        path = files / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        path.chmod(mode)

    logo_name = f'usr/share/pixmaps/{identity}-login.png'
    key_name = f'zz-{identity}'
    config = "[org/gnome/login-screen]\nlogo='/" + logo_name + "'\nbanner-message-enable=false\n"
    if 'fallback-logo' in keys_available:
        config += "fallback-logo='/" + logo_name + "'\n"
    write(KEYROOT + '/' + key_name, config)
    helper_name = f'usr/local/sbin/{identity}-prepare-login'
    write(helper_name, PREPARE.replace('BRAND_ID', identity), 0o755)
    write(f'etc/systemd/system/gdm.service.d/zz-{identity}.conf',
          '# Load after the NVIDIA ExecStartPre reset.\n[Service]\nExecStartPre=+/' + helper_name + '\n')
    font_path = font_path or subprocess.check_output(
        ['fc-match', '-f', '%{file}', 'DejaVu Sans:style=Bold'], text=True)
    font = ImageFont.truetype(str(font_path), font_size)
    bounds = font.getbbox(tag)
    width, height = bounds[2] - bounds[0] + 48, bounds[3] - bounds[1] + 32
    require(width <= 1800, 'Tag is too wide for a login logo; reduce text or font size')
    logo = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(logo).text((24 - bounds[0], 16 - bounds[1]), tag, font=font, fill=color)
    (files / logo_name).parent.mkdir(parents=True, exist_ok=True)
    logo.save(files / logo_name)
    (files / logo_name).chmod(0o644)
    preview = Image.new('RGB', (width + 80, height + 80), '#242424')
    preview.paste(logo, (40, 40), logo)
    preview.save(output / 'preview.png')

    def body(name, seen=()):
        require(name not in seen, f'Keyfile symlink loop: {name}')
        meta = members.get(name)
        require(meta is not None, f'Uninspected keyfile target: {name}; add it to inspection')
        if meta['type'] == '0':
            return (inspection / name).read_bytes()
        require(meta['type'] == '2', f'Unsupported keyfile type: {name}')
        target = meta['linkname']
        target = target[1:] if target.startswith('/') else posixpath.join(posixpath.dirname(name), target)
        return body(normalize(target), (*seen, name))

    keydir = output / 'keyfiles'
    keydir.mkdir()
    for name, meta in members.items():
        if name.startswith(KEYROOT + '/') and meta['type'] != '5':
            relative = name[len(KEYROOT) + 1:]
            destination = keydir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(body(name))
    preserved = '# Preserve the target cached defaults.\n' + settings(inspection / DATABASE)
    preserve_name = f'10-{identity}-preserved-defaults'
    write(KEYROOT + '/' + preserve_name, preserved)
    (keydir / preserve_name).write_text(preserved)
    (keydir / key_name).write_text(config)
    require(key_name == max(p.name for p in keydir.iterdir() if p.is_file()),
            'Another keyfile sorts after this tag; choose/adapt the override filename')
    database = files / DATABASE
    database.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['dconf', 'compile', str(database), str(keydir)], check=True)
    database.chmod(0o644)
    old, new = parse_settings(settings(inspection / DATABASE)), parse_settings(settings(database))
    changes = {'org/gnome/login-screen/logo', 'org/gnome/login-screen/banner-message-enable'}
    if 'fallback-logo' in keys_available:
        changes.add('org/gnome/login-screen/fallback-logo')
    require(all(new.get(key) == value for key, value in old.items() if key not in changes),
            'Compiled payload changed an unrelated target setting')
    require(new.get('org/gnome/login-screen/logo') == "'/" + logo_name + "'", 'Logo did not take effect')
    require(new.get('org/gnome/login-screen/banner-message-enable') == 'false', 'Banner was not disabled')
    subprocess.run(['sh', '-n', str(files / helper_name)], check=True)
    manifest = {str(p.relative_to(files)): dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                mode=p.stat().st_mode & 0o777) for p in files.rglob('*') if p.is_file()}
    save(output / 'manifest.json', manifest)
    save(output / 'branding.json', dict(tag=tag, identity=identity, dimensions=[width, height],
                                       inspection=str(inspection), hardware_verified=False))
    print(f'PASS {tag}: {width}x{height} logo, compiled DB, preserved settings; {output}', flush=True)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--id', default='jetson-login', dest='identity')
    parser.add_argument('--font-size', type=int, default=40)
    parser.add_argument('--color', default='#22d3ee')
    parser.add_argument('--font', type=Path)
    args = parser.parse_args()
    build(args.inspection, args.output, args.tag, args.identity, args.font_size, args.color, args.font)
