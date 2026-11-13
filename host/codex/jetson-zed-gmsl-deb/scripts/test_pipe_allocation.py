"""Regression retained from stable 1.4.4.4; set ZEDX_PIPE_SOURCE to actual C.

Exercise the real allocator with host stubs; no camera hardware is touched.
The test covers pipe allocation only, not physical routing or model support.
"""
import os
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = None

STUBS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef uint8_t u8;
typedef int8_t s8;
typedef uint16_t u16;
#define N_SER_PIPES 4
#define N_DSER_PIPES 8
#define GMSL_PIPES_01_REG 0xf0
#define ZEDX 0
#define ZEDXNANO 5
#define dev_info(...) ((void)0)
#define dev_dbg(...) ((void)0)
#define dev_warn(...) ((void)0)
struct list_head { struct list_head *next; };
#define list_entry(ptr, type, member) \
    ((type *)((char *)(ptr) - offsetof(type, member)))
struct i2c_client { int dev; };
struct sensor {
    struct list_head list;
    int i2c_bus, dts_cam_index, dts_cam_model, detection_id, dsr_pipe;
    bool is_second_cam_from_i2c;
    s8 pipes[4];
};
struct max96712 {
    struct i2c_client *i2c_client;
    int n_cam, avail_pipe, phy_idx_bound;
    unsigned char csi_rate_reg_val[4];
    unsigned long long csi_rate_bps[4];
    struct sensor detected_sensors[8];
    unsigned int *regmap;
};
static u8 cam_pipes[] = {3, 1, 2, 1, 3, 3};
static int calls, allocated[8], source_pipe[8];
static int regmap_read(unsigned int *map, int reg, unsigned int *value) {
    assert(reg >= 0xf0 && reg <= 0xf3);
    *value = map[reg - 0xf0];
    return 0;
}
static int regmap_write(unsigned int *map, int reg, unsigned int value) {
    assert(reg >= 0xf0 && reg <= 0xf3);
    map[reg - 0xf0] = value;
    return 0;
}
static int setup_sensor_pipe(struct max96712 *priv, struct sensor *sensor,
                             u8 pipe, int model) {
    (void)priv; (void)model;
    assert(calls < 8);
    allocated[calls] = sensor->pipes[pipe];
    source_pipe[calls++] = pipe;
    sensor->dsr_pipe = sensor->pipes[pipe];
    return 0;
}
'''

HARNESS = r'''
int main(int argc, char **argv) {
    assert(argc == 2);
    int scenario = atoi(argv[1]);
    struct i2c_client client = {0};
    unsigned int regs[4] = {0};
    struct max96712 priv = {.i2c_client = &client, .regmap = regs};
    struct sensor sensors[9] = {0};
    int models[4] = {1, 0, 1, 0};
    int buses[4] = {0, 0, 0, 0};
    int expected_sources[8] = {0, 2, 3, 0, 2, 3};
    int cameras = 4, expected = 6;
    if (scenario == 1) {
        /* The other physical order: stereo, mono, stereo, mono. */
        int m[] = {0, 1, 0, 1}, s[] = {0, 1, 2, 0, 1, 2};
        for (int i=0; i<4; ++i) models[i] = m[i];
        for (int i=0; i<6; ++i) expected_sources[i] = s[i];
    } else if (scenario == 2) {
        /* Original reference topology: two separate mux segments. */
        buses[2] = buses[3] = 1;
    } else if (scenario == 3) {
        cameras = 2; models[0] = models[1] = 0; expected = 4;
        int s[] = {0, 1, 2, 3};
        for (int i=0; i<4; ++i) expected_sources[i] = s[i];
    } else if (scenario == 4) {
        /* Mixed serializer tables, including the Y-only 4K source. */
        int m[] = {2, 3, 5, 4}, s[] = {1, 2, 0, 1, 2, 3};
        for (int i=0; i<4; ++i) models[i] = m[i];
        for (int i=0; i<6; ++i) expected_sources[i] = s[i];
    } else if (scenario == 5) {
        /* Four stereo cameras fill all eight deserializer pipes. */
        expected = 8;
        for (int i=0; i<4; ++i) models[i] = 0;
        int s[] = {0, 1, 2, 3, 0, 1, 2, 3};
        for (int i=0; i<8; ++i) expected_sources[i] = s[i];
    }
    int first[4], cursor = 0;
    for (int camera=0; camera<cameras; ++camera) {
        first[camera] = cursor;
        int eyes = (models[camera] == 0 || models[camera] == 4 || models[camera] == 5) ? 2 : 1;
        for (int eye=0; eye<eyes; ++eye) {
            struct sensor *sensor = &sensors[cursor++];
            sensor->i2c_bus = buses[camera];
            sensor->dts_cam_index = camera;
            sensor->dts_cam_model = models[camera];
            sensor->dsr_pipe = -1;
        }
    }
    for (int i=0; i<cursor; ++i) sensors[i].list.next = &sensors[i+1].list;
    sensors[cursor].dts_cam_index = -1;
    for (int camera=0; camera<cameras; ++camera) {
        struct sensor *sensor = &sensors[first[camera]];
        assert(sl_max96712_pipes_setup(&priv, sensor, models[camera], camera) == 0);
        priv.detected_sensors[priv.n_cam++] = *sensor;
    }
    if (calls != expected || priv.avail_pipe != expected) {
        fprintf(stderr, "only %d/%d video pipes allocated\n", calls, expected);
        return 1;
    }
    for (int i=0; i<expected; ++i) {
        if (allocated[i] != i || source_pipe[i] != expected_sources[i]) {
            fprintf(stderr, "pipe %d: destination=%d source=%d expected_source=%d\n",
                i, allocated[i], source_pipe[i], expected_sources[i]);
            return 1;
        }
    }
    printf("scenario=%d sensors=%d enable_mask=0x%02x PASS\n",
           scenario, expected, 0xff >> (8 - priv.avail_pipe));
    return 0;
}
'''


class PipeAllocation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text()
        start = source.index('static int sl_max96712_pipes_setup(')
        brace = source.index('{', start)
        depth, end = 1, brace + 1
        while depth:
            depth += (source[end] == '{') - (source[end] == '}')
            end += 1
        cls.directory = tempfile.TemporaryDirectory(prefix='zed-pipe-regression-')
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        (path / 'allocator.c').write_text(STUBS + source[start:end] + HARNESS)
        cls.binary = path / 'allocator'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Wno-unused-variable',
                        '-Wno-unused-but-set-variable', '-fsanitize=undefined,address',
                        '-g', str(path / 'allocator.c'), '-o', str(cls.binary)], check=True)

    def test_video_routing_and_serializer_tables(self):
        for scenario in range(6):
            with self.subTest(scenario=scenario):
                result = subprocess.run([str(self.binary), str(scenario)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(result.stdout.strip())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=os.environ.get('ZEDX_PIPE_SOURCE'))
    args = parser.parse_args()
    if args.source is None:
        parser.error('Pass --source or set ZEDX_PIPE_SOURCE to the actual sl_max96712.c')
    SOURCE = Path(args.source)
    unittest.main(argv=[sys.argv[0]])
