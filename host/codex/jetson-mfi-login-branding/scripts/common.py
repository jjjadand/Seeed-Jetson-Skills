"""Shared helpers for the GDM MFI tools. No commands run on import."""
import hashlib
import json
import posixpath
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha1(path):
    result = hashlib.sha1()
    with Path(path).open('rb') as source:
        for data in iter(lambda: source.read(8 * 1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def normalize(name):
    require(not name.startswith('/'), f'Absolute archive name: {name}')
    normalized = posixpath.normpath(name)
    require(normalized != '..' and not normalized.startswith('../'), f'Archive path escapes root: {name}')
    return normalized


def app_row(text, image_name):
    matches = []
    for index, line in enumerate(text.splitlines(keepends=True)):
        fields = line.rstrip('\n').split(',')
        if len(fields) >= 8 and fields[4].strip() == image_name:
            require(fields[1].strip().endswith(':APP'), 'Image index entry is not APP')
            matches.append((index, fields))
    require(len(matches) == 1, 'Expected exactly one APP index entry')
    return matches[0]


def discover(mfi):
    mfi = Path(mfi).resolve()
    external = mfi / 'tools/kernel_flash/images/external'
    config = {}
    for line in (external / 'flash.cfg').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            config[key.strip()] = value.strip().strip('\"\'')
    name = config.get('APP_ext', '')
    require(name and Path(name).name == name, 'Expected APP_ext as a plain external image filename')
    image = external / name
    require(image.is_file() and not image.is_symlink(), 'APP must be a regular image file')
    expected = (external / (name + '.sha1sum')).read_text().split()[0]
    _, row = app_row((external / 'flash.idx').read_text(), name)
    require(row[-1].strip() == expected, 'APP checksums disagree before modification')
    return mfi, external, image, expected
