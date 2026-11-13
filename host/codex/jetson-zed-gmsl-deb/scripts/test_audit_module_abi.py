"""Host-only regressions for the reusable audit helper; no Jetson needed."""
import argparse
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import audit_module_abi as abi


class VersionFormats(unittest.TestCase):
    def test_fixed64(self):
        data = struct.pack('<Q56s', 0x12345678, b'tegracam_device_register\0')
        self.assertEqual(abi.parse_versions(data), ('fixed64', {'tegracam_device_register': 0x12345678}))

    def test_ubuntu_variable(self):
        name = b'tegracam_device_register\0'
        step = (8 + len(name) + 3) & ~3
        data = struct.pack('<II', step, 0xaabbccdd) + name.ljust(step - 8, b'\0')
        self.assertEqual(abi.parse_versions(data), ('ubuntu-variable', {'tegracam_device_register': 0xaabbccdd}))

    def test_bad_records_fail(self):
        for data in (b'', b'\0' * 64, struct.pack('<II', 1000, 5) + b'x\0'):
            with self.subTest(data=data), self.assertRaises(abi.AuditError):
                abi.parse_versions(data)

    def test_no_export_is_not_failure(self):
        with mock.patch.object(abi, 'elf_sections', return_value={'.text': b'abc'}), \
             mock.patch.object(abi, 'run') as run:
            self.assertEqual(abi.actual_exports(Path('sensor.ko')), {})
            run.assert_not_called()


class ProviderPriority(unittest.TestCase):
    def test_real_provider_rejects_stale_crc(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table, candidate, camera = root / 'Module.symvers', root / 'sensor.ko', root / 'camera.ko'
            table.write_text('0x11111111\ttegracam_device_register\tNVIDIA/camera\tEXPORT_SYMBOL\t\n')
            candidate.write_bytes(b'candidate')
            camera.write_bytes(b'actual-provider')
            args = argparse.Namespace(kernel='5.15-test', symvers=[table], provider_module=[camera],
                                      module=[candidate], root=None)
            with mock.patch.object(abi, 'actual_exports', side_effect=lambda p: {'tegracam_device_register': 0x22222222} if p == camera else {}), \
                 mock.patch.object(abi, 'run', return_value='5.15-test SMP aarch64'), \
                 mock.patch.object(abi, 'module_versions', return_value=('fixed64', {'tegracam_device_register': 0x11111111})):
                report = abi.audit(args)
            self.assertFalse(report['passed'])
            self.assertEqual(report['modules'][0]['failures'][0]['provider_crc'], '0x22222222')
            self.assertEqual(len(report['provider_overrides']), 1)
            with mock.patch.object(abi, 'actual_exports', side_effect=lambda p: {'tegracam_device_register': 0x22222222} if p == camera else {}), \
                 mock.patch.object(abi, 'run', return_value='5.15-test SMP aarch64'), \
                 mock.patch.object(abi, 'module_versions', return_value=('fixed64', {'tegracam_device_register': 0x22222222})):
                self.assertTrue(abi.audit(args)['passed'])


class DependencyClosure(unittest.TestCase):
    def test_declared_dependency_omission_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sensor = root / 'sensor.ko'
            sensor.write_bytes(b'x')

            def run(*args):
                if args[0] == 'modprobe':
                    return 'insmod ' + str(sensor)
                if '-F' in args and 'name' in args:
                    return 'sensor'
                if '-F' in args and 'depends' in args:
                    return 'tegra-camera'
                return str(sensor)

            with mock.patch.object(abi, 'run', side_effect=run), self.assertRaisesRegex(abi.AuditError, 'Missing declared dependency'):
                abi.dependency_paths(root, '5.15-test', {sensor})

    def test_wrong_selected_module_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, stale = root / 'new.ko', root / 'old.ko'
            candidate.write_bytes(b'new')
            stale.write_bytes(b'old')
            with mock.patch.object(abi, 'module_name', return_value='sensor'), \
                 mock.patch.object(abi, 'selected_path', return_value=stale), \
                 self.assertRaisesRegex(abi.AuditError, 'different copy'):
                abi.dependency_paths(root, '5.15-test', {candidate})


if __name__ == '__main__':
    unittest.main()
