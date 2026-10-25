"""The shared motor presentation ages evidence without turning cache reads into fresh telemetry."""
from pathlib import Path
import shutil
import subprocess

import pytest

COMMON = Path(__file__).parents[1]


def test_motor_health_evidence_clock_fault_retention_and_unknown_values():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required')
    script = r"""
      import assert from 'node:assert/strict';
      import {createMotorHealthState,renderMotorHealthSummary} from './motor-health.js';
      const state = createMotorHealthState();
      const sample = {schema_version:'rosy.motor-health.v1',status:'active',evidence:'fresh',
        sample_age_s:.2,stale_after_s:2,motors:[{group:'arm_a',joint:'shoulder_lift',id:12,
        sample_age_s:.2,command_raw:2028,present_raw:2028,error_deg:0,pwm:-391,pwm_limit:400,
        pwm_utilization:.9775,temperature_c:65,temperature_limit_c:70,voltage_v:12,
        min_voltage_v:6,max_voltage_v:14,warnings:['high_pwm','near_temperature_limit']}],stop_reasons:[]};
      state.accept(sample, {receivedAtMs:1000,cacheAgeS:.5});
      assert.equal(state.read(1000).evidence,'fresh');
      assert.equal(state.read(2500).evidence,'delayed');
      assert.equal(state.read(2500).motors[0].evidence,'delayed');
      assert.equal(state.read(1000).severity,'warn');
      state.accept({...sample,status:'fault',stop_reasons:['ID12 overload']},{receivedAtMs:3000});
      assert.equal(state.read(3000).severity,'crit');
      assert.notEqual(state.read(3000).evidence,'fresh');
      state.accept({schema_version:'rosy.motor-health.v1',status:'unavailable',evidence:'unavailable',
        support_reason:'No wheel telemetry',motors:[]},{receivedAtMs:4000});
      assert.equal(state.read(4000).evidence,'unavailable');
      assert.equal(state.read(4000).lastFault,'ID12 overload');
      assert.equal(state.read(4000).supportReason,'No wheel telemetry');
      state.accept(sample,{receivedAtMs:5000});
      state.disconnect();
      assert.equal(state.read(6000).evidence,'disconnected');
      assert.equal(state.read(6000).lastFault,'ID12 overload');
      state.accept({...sample,sample_age_s:null},{receivedAtMs:7000});
      assert.equal(state.read(7000).evidence,'unavailable');
      state.accept({...sample,motors:[{...sample.motors[0],sample_age_s:9}]},{receivedAtMs:8000});
      assert.equal(state.read(8000).motors[0].evidence,'delayed');
      state.accept(sample,{receivedAtMs:9000,cacheAgeS:null});
      assert.equal(state.read(9000).evidence,'unavailable');
      state.accept({...sample,status:'ended'},{receivedAtMs:9000});
      assert.notEqual(state.read(9000).evidence,'fresh');
      const root={classList:{add(){}},dataset:{}};
      state.accept(sample,{receivedAtMs:10000});
      renderMotorHealthSummary(root,state.read(10000));
      assert.ok(root.textContent.includes('주의 모터 1개')); // two warnings still belong to one motor
      assert.ok(root.textContent.includes('A 팔 ID 12: PWM 사용률 높음'));
      state.accept({...sample,motors:[...sample.motors,{...sample.motors[0],group:'arm_b'}]},
        {receivedAtMs:10000});
      renderMotorHealthSummary(root,state.read(10000));
      assert.ok(root.textContent.includes('주의 모터 2개')); // same ID on two arms is two motors
      renderMotorHealthSummary(root,state.read(13000));
      assert.ok(root.textContent.includes('마지막 관측'));
      assert.ok(root.textContent.includes('주의 모터 2개'));
      state.accept({...sample,status:'fault',stop_reasons:['ID12 overload'],
        motors:[{...sample.motors[0],warnings:[]}]},{receivedAtMs:14000});
      renderMotorHealthSummary(root,state.read(14000));
      assert.ok(root.textContent.includes('중단 기록'));
      assert.ok(root.textContent.includes('ID12 overload'));
      assert.ok(!root.textContent.includes('0개'));
      assert.ok(!root.textContent.includes('PWM 사용률 높음'));
      state.accept({...sample,status:'fault',stop_reasons:['hardware shutdown'],
        motors:[{...sample.motors[0],hardware_error:32,warnings:[]}]},{receivedAtMs:15000});
      renderMotorHealthSummary(root,state.read(15000));
      assert.ok(root.textContent.includes('고장 모터 1개'));
      assert.ok(root.textContent.includes('A 팔 ID 12 오류 32'));
      assert.ok(root.textContent.includes('hardware shutdown'));
      state.accept({schema_version:'rosy.motor-health.v1',status:'unavailable',evidence:'unavailable',motors:[]},
        {receivedAtMs:16000});
      assert.ok(state.read(16000).lastFault.includes('A 팔 ID 12 하드웨어 오류 32'));
    """
    done = subprocess.run([node,'--input-type=module','--eval',script],cwd=COMMON,
                          capture_output=True,text=True,check=False)
    assert done.returncode == 0, done.stdout + done.stderr
