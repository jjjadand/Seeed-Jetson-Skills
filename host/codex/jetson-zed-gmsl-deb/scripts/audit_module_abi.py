#!/usr/bin/env python3
"""Audit uncompressed ARM64 module CRCs and an optional staged dependency tree.

Only --output writes a report. This tool never loads modules or runs depmod.
Header/type compatibility must be established separately from the CRC audit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys


class AuditError(RuntimeError):
    pass


def run(*args):
    process = subprocess.run([str(x) for x in args], text=True, capture_output=True)
    if process.returncode:
        raise AuditError(f"{args[0]} exited {process.returncode}: {process.stderr.strip()}")
    return process.stdout.strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, reason):
    if not condition:
        raise AuditError(str(reason))


def symbol_name(raw):
    require(b'\0' in raw, 'Version symbol has no terminator')
    name = raw.split(b'\0', 1)[0].decode('ascii')
    require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.$]*', name), f'Invalid symbol: {name!r}')
    return name


def elf_sections(path):
    data = path.read_bytes()
    require(data[:6] == b'\x7fELF\x02\x01', f'Expected uncompressed ELF64 little endian .ko: {path}')
    require(struct.unpack_from('<H', data, 18)[0] == 183, f'Expected AArch64 module: {path}')
    offset = struct.unpack_from('<Q', data, 40)[0]
    size, count, names_index = struct.unpack_from('<HHH', data, 58)
    require(size >= 64 and count > 0 and names_index < count, f'Unsupported ELF section table: {path}')
    require(offset + size * count <= len(data), f'Truncated ELF table: {path}')
    records = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * size) for i in range(count)]
    names_record = records[names_index]
    names = data[names_record[4]:names_record[4] + names_record[5]]
    sections = {}
    for record in records:
        name = names[record[0]:].split(b'\0', 1)[0].decode()
        if record[1] == 8:  # SHT_NOBITS is not data in the file.
            continue
        require(record[4] + record[5] <= len(data), f'Truncated section {name}: {path}')
        sections[name] = data[record[4]:record[4] + record[5]]
    return sections


def parse_versions(data):
    """Accept the R36 64-byte ABI and R39 Ubuntu variable-length record ABI."""
    require(bool(data), 'Empty __versions is not a CRC verification')
    candidates = []
    if len(data) % 64 == 0:
        try:
            result = {}
            for cursor in range(0, len(data), 64):
                crc = struct.unpack_from('<Q', data, cursor)[0]
                require(crc <= 0xffffffff, 'CRC is not 32 bits')
                name = symbol_name(data[cursor + 8:cursor + 64])
                require(name not in result, 'Duplicate version symbol')
                result[name] = crc
            candidates.append(('fixed64', result))
        except (AuditError, UnicodeError):
            pass
    try:
        cursor = 0
        result = {}
        while cursor < len(data):
            if not any(data[cursor:]):
                break
            require(cursor + 8 <= len(data), 'Truncated variable record')
            step, crc = struct.unpack_from('<II', data, cursor)
            require(12 <= step <= len(data) - cursor and step % 4 == 0, 'Invalid variable record length')
            name = symbol_name(data[cursor + 8:cursor + step])
            require(name not in result, 'Duplicate version symbol')
            result[name] = crc
            cursor += step
        require(bool(result), 'No variable records')
        candidates.append(('ubuntu-variable', result))
    except (AuditError, UnicodeError):
        pass
    require(len(candidates) == 1, 'Unrecognized or ambiguous __versions; do not skip CRC verification')
    return candidates[0]


def module_versions(path):
    sections = elf_sections(path)
    require('__versions' in sections, f'No supported modversions section in {path}')
    return parse_versions(sections['__versions'])


def symvers(path):
    result = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if not fields:
            continue
        require(len(fields) >= 3, f'Invalid Module.symvers line in {path}')
        name, crc = fields[1], int(fields[0], 16)
        require(name not in result or result[name] == crc, f'Conflicting {name} within {path}')
        result[name] = crc
    require(bool(result), f'Empty symbol table: {path}')
    return result


def actual_exports(path):
    sections = elf_sections(path)
    # kmod reports ENOENT for a valid module that exports no symbols.
    if not any(value for name, value in sections.items()
               if name == '__ksymtab' or (name.startswith('__ksymtab_') and name != '__ksymtab_strings')):
        return {}
    result = {}
    for line in run('modprobe', '--show-exports', path).splitlines():
        fields = line.split()
        require(len(fields) == 2, f'Unrecognized kmod export record: {line!r}')
        require(re.fullmatch(r'0x[0-9a-fA-F]+', fields[0]), f'Invalid export CRC: {line!r}')
        result[fields[1]] = int(fields[0], 16)
    return result


def module_name(path):
    return run('modinfo', '-F', 'name', path).replace('-', '_')


def selected_path(root, kernel, name):
    value = run('modinfo', '-b', root, '-k', kernel, '-n', name)
    require(value != '(builtin)', f'Seed unexpectedly resolves to builtin: {name}')
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    # kmod versions can emit either staged absolute paths or /lib/modules paths.
    if not path.is_file():
        path = root / value.lstrip('/')
    require(path.is_file(), f'Selected module missing: {value}')
    require(path.resolve().is_relative_to(root.resolve()), f'Module escaped staged root: {path}')
    return path.resolve()


def dependency_paths(root, kernel, seeds):
    paths = set()
    builtin = set()
    for seed in seeds:
        name = module_name(seed)
        chosen = selected_path(root, kernel, name)
        require(digest(chosen) == digest(seed), f'depmod selected a different copy of {name}: {chosen}')
        listing = run('modprobe', '-d', root, '-S', kernel, '-C', '/dev/null', '--show-depends', name)
        for line in listing.splitlines():
            fields = line.split()
            require(bool(fields), 'Empty dependency record')
            if fields[0] == 'builtin':
                builtin.add(Path(fields[1]).name.split('.ko')[0].replace('-', '_'))
            elif fields[0] == 'insmod':
                path = Path(fields[1])
                if not path.is_file():
                    path = root / fields[1].lstrip('/')
                require(path.is_file() and path.resolve().is_relative_to(root.resolve()),
                        f'Unresolved or out-of-root dependency: {line}')
                paths.add(path.resolve())
            else:
                raise AuditError(f'Unexpected dependency action; inspect configuration: {line}')
    for base in (root / 'lib/modules' / kernel, root / 'usr/lib/modules' / kernel):
        table = base / 'modules.builtin'
        if table.is_file():
            builtin.update(Path(line).name.split('.ko')[0].replace('-', '_')
                           for line in table.read_text().splitlines())
    names = {module_name(path) for path in paths}
    require({module_name(path) for path in seeds} <= names, 'Dependency output omitted a seed')
    for path in paths:
        for name in run('modinfo', '-F', 'depends', path).split(','):
            if not name:
                continue
            normalized = name.replace('-', '_')
            require(normalized in names or normalized in builtin,
                    f'Missing declared dependency: {path.name} -> {name}; merge both module trees')
            if normalized not in builtin:
                chosen = selected_path(root, kernel, name)
                require(chosen in paths, f'Dependency selection mismatch: {name}')
    return paths


def audit(args):
    report = {'kernel': args.kernel, 'hardware_tested': False, 'type_layout_verified_by_this_tool': False,
              'symvers': [], 'actual_providers': [], 'provider_overrides': [], 'modules': [], 'errors': []}
    providers = {}
    for path in args.symvers:
        providers.update(symvers(path))
        report['symvers'].append({'path': str(path), 'sha256': digest(path)})
    seeds = {path.resolve() for path in args.module}
    paths = dependency_paths(args.root.resolve(), args.kernel, seeds) if args.root else seeds
    actual_paths = {path.resolve() for path in args.provider_module} | paths
    actual = {}
    for path in sorted(actual_paths):
        exports = actual_exports(path)
        for name, crc in exports.items():
            require(name not in actual or actual[name][0] == crc,
                    f'Conflicting actual providers for {name}: {actual.get(name)} and {path}')
            if name in providers and providers[name] != crc:
                report['provider_overrides'].append({'symbol': name, 'symvers_crc': hex(providers[name]),
                                                     'actual_crc': hex(crc), 'provider': str(path)})
            actual[name] = (crc, path)
        report['actual_providers'].append({'path': str(path), 'sha256': digest(path), 'exports': len(exports)})
    providers.update({name: value[0] for name, value in actual.items()})
    for path in sorted(paths):
        magic = run('modinfo', '-F', 'vermagic', path)
        require(magic.split()[0] == args.kernel, f'Kernel mismatch: {path}: {magic}')
        encoding, imports = module_versions(path)
        failures = []
        for name, crc in imports.items():
            expected = providers.get(name)
            if expected != crc:
                failures.append({'symbol': name, 'required_crc': hex(crc),
                                 'provider_crc': None if expected is None else hex(expected)})
        report['modules'].append({'path': str(path), 'sha256': digest(path), 'vermagic': magic,
                                  'versions_encoding': encoding, 'import_crc_checks': len(imports),
                                  'failures': failures})
        if failures:
            report['errors'].append(f'{path.name}: {len(failures)} unresolved/mismatched CRCs')
    report['dependency_closure_checked'] = args.root is not None
    report['passed'] = not report['errors']
    report['module_count'] = len(paths)
    report['crc_checks'] = sum(m['import_crc_checks'] for m in report['modules'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', required=True, help='Exact target uname -r')
    parser.add_argument('--symvers', action='append', type=Path, default=[], help='Ordered baseline tables; repeat allowed')
    parser.add_argument('--provider-module', action='append', type=Path, default=[], help='Actual provider ko; overrides baseline CRCs')
    parser.add_argument('--module', action='append', type=Path, required=True, help='Uncompressed ARM64 candidate ko; repeat allowed')
    parser.add_argument('--root', type=Path, help='Already merged temporary rootfs with depmod indexes; audited read-only')
    parser.add_argument('--output', type=Path, help='Optional JSON report; this is the only written file')
    args = parser.parse_args()
    try:
        report = audit(args)
    except (AuditError, OSError, ValueError, UnicodeError, struct.error) as error:
        report = {'passed': False, 'errors': [str(error)], 'hardware_tested': False}
    output = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(output)
    print(output, end='')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
