"""Fault injection against the compiled driver; isolated ROS domain, no hardware."""
import os
from pathlib import Path
import subprocess
import time

import pytest


@pytest.fixture(scope='module')
def driver(tmp_path_factory):
    executable = os.environ.get('BNO055_TEST_EXECUTABLE')
    if not executable:
        pytest.skip('Set BNO055_TEST_EXECUTABLE to the built ARM64 driver')
    folder = tmp_path_factory.mktemp('bno055-faults')
    source = folder / 'bus.c'
    source.write_text(r'''
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>
static double reset_at = 0;
static int units_configured = 0;
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec+t.tv_nsec/1e9; }
int wiringPiI2CSetupInterface(const char *path, int address) { (void)path; (void)address; return 999; }
int wiringPiI2CReadReg8(int fd, int reg) {
 (void)fd;
 if (strcmp(getenv("BNO_FAULT"), "absent") == 0) return -1;
 if (reset_at && strcmp(getenv("BNO_FAULT"), "reset_nack") == 0) return -1;
 if (reset_at && now()-reset_at < .650) return -1;
 if (reg == 0) return 0xa0;
 if (reg == 0x34) return 25;
 if (reg == 0x35) return 0xfc;
 if (reg == 0x36) return 0x0f;
 if (reg == 0x3a) return 0;
 if (reg == 0x39) return strcmp(getenv("BNO_FAULT"), "fusion_stuck") == 0 ? 0 : 5;
 return 0;
}
int wiringPiI2CWriteReg8(int fd, int reg, int value) {
 (void)fd;
 if (reg == 0x3b) {
  if (strcmp(getenv("BNO_FAULT"), "units_write_failure") == 0) { errno=EIO; return -1; }
  units_configured = value == 0;
 }
 if (reg == 0x3f && value == 0x20) reset_at=now();
 return 0;
}
int wiringPiI2CReadBlockData(int fd, int reg, uint8_t *data, uint8_t size) {
 (void)fd; (void)reg; (void)size;
 if (!units_configured) return -1;
 memset(data, 0, 32);
 if (strcmp(getenv("BNO_FAULT"), "short_read") == 0) return 31;
 if (strcmp(getenv("BNO_FAULT"), "invalid_orientation") == 0) return 32;
 if (strcmp(getenv("BNO_FAULT"), "healthy") == 0) { data[25]=0x40; data[4]=0xd5; data[5]=3; return 32; }
 return -1;
}
''')
    library = folder / 'bus.so'
    subprocess.run(['cc', '-shared', '-fPIC', str(source), '-o', str(library)], check=True)
    return executable, library


def run_fault(driver, mode, timeout, reset_on_start=False):
    executable, library = driver
    env = dict(os.environ, LD_PRELOAD=str(library), BNO_FAULT=mode,
               ROS_DOMAIN_ID='231', ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
    command = [executable]
    if reset_on_start:
        command += ['--ros-args', '-p', 'reset_on_start:=true']
    return subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout)


@pytest.mark.parametrize('reset_on_start', [False, True])
def test_absent_chip_exits_instead_of_hanging_or_resetting(driver, reset_on_start):
    started = time.monotonic()
    result = run_fault(driver, 'absent', 5, reset_on_start=reset_on_start)
    assert result.returncode == 1
    assert 'chip ID unavailable; refusing reset' in result.stderr
    assert 'stage=reset' not in result.stderr
    assert time.monotonic() - started < 5


def test_fusion_start_has_bounded_timeout(driver):
    result = run_fault(driver, 'fusion_stuck', 10)
    assert result.returncode == 1
    assert 'fusion_start timed out' in result.stderr


@pytest.mark.parametrize('mode,message', [
    ('read_failure', 'measurement read failed; no IMU sample published'),
    ('short_read', 'measurement read failed; no IMU sample published'),
    ('invalid_orientation', 'invalid orientation; no IMU sample published'),
])
def test_failed_measurement_is_not_published_as_zero_sample(driver, mode, message):
    with pytest.raises(subprocess.TimeoutExpired) as error:
        run_fault(driver, mode, 4)
    output = (error.value.stderr or b'').decode()
    assert message in output
    assert 'first_valid_sample=true' not in output


def test_healthy_initialization_reaches_stream(driver):
    with pytest.raises(subprocess.TimeoutExpired) as error:
        run_fault(driver, 'healthy', 4)
    output = (error.value.stderr or b'').decode()
    assert 'stage=reset_skipped reason=reset_on_start_false' in output
    assert 'stage=reset reg=' not in output
    assert 'stage=reset_wait' not in output
    assert 'stage=ready fusion=IMUPLUS' in output
    assert 'stage=units reg=0x3b actual=0 errno=0' in output
    assert 'stage=stream first_valid_sample=true' in output


def test_explicit_reset_retains_quiet_wait_and_stream(driver):
    with pytest.raises(subprocess.TimeoutExpired) as error:
        run_fault(driver, 'healthy', 4, reset_on_start=True)
    output = (error.value.stderr or b'').decode()
    assert 'stage=reset reg=0x3f actual=32' in output
    assert 'stage=reset_wait duration_ms=700' in output
    assert 'stage=stream first_valid_sample=true' in output


def test_explicit_reset_followed_by_nack_has_bounded_timeout(driver):
    result = run_fault(driver, 'reset_nack', 5, reset_on_start=True)
    assert result.returncode == 1
    assert 'stage=reset reg=0x3f actual=32' in result.stderr
    assert 'chip_boot timed out' in result.stderr
    assert 'stage=stream' not in result.stderr


def test_units_write_failure_stops_initialization(driver):
    result = run_fault(driver, 'units_write_failure', 5)
    assert result.returncode == 1
    assert 'stage=units reg=0x3b actual=-1' in result.stderr
    assert 'stage=ready' not in result.stderr
    assert 'stage=stream' not in result.stderr
