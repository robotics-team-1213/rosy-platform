"""The shared HOLD diagnostic probe the station HTTP SIMs install (station_readback_probe.py)."""
import asyncio
import json
from types import SimpleNamespace


def test_hold_probe_preserves_nested_exception_and_original_hold(capsys):
    import sys
    import station_readback_probe

    install = getattr(station_readback_probe, 'install_hold_probe', None)
    assert callable(install), 'caught HOLD exceptions need a shared diagnostic probe'
    current, intent, result = SimpleNamespace(session_id='charge-probe'), object(), object()
    calls = []

    async def original(current, reason, **kwargs):
        calls.append((current, reason, kwargs, sys.exception()))
        return result

    motion = SimpleNamespace(stop_hold=original)
    install(motion, lambda: 123.5)

    async def nested(reason):
        await asyncio.sleep(0)
        return await motion.stop_hold(current, reason, intent=intent)

    async def read_return(error):
        view = dict(state='FAILED', reason='SIM_TRIP_FAILURE', detail={'phase': 'arrival'},
            forbidden='MUST_NOT_BE_REPORTED')
        raise error

    async def run():
        for reason in ('CHARGE_MOTION_READBACK_UNAVAILABLE', 'CHARGE_DEPARTURE_UNVERIFIED'):
            error = ValueError('original readback failure')
            try:
                await read_return(error)
            except ValueError:
                assert await nested(reason) is result
                assert sys.exception() is error
            prefix, payload = capsys.readouterr().out.strip().split(' ', 1)
            report = json.loads(payload)
            assert prefix == 'STATION_HOLD_DIAGNOSTIC'
            assert report['session_id'] == current.session_id and report['reason'] == reason
            assert report['clock'] == 123.5
            assert report['exception_type'] == 'ValueError'
            assert report['exception'] == str(error)
            assert 'raise error' in ''.join(report['traceback'])
            assert report.get('return_trip') == dict(state='FAILED', reason='SIM_TRIP_FAILURE',
                detail={'phase': 'arrival'})
            assert 'MUST_NOT_BE_REPORTED' not in payload
            assert calls[-1] == (current, reason, {'intent': intent}, error)
        assert await nested('CHARGE_MOTION_READBACK_UNAVAILABLE') is result
        assert calls[-1] == (current, 'CHARGE_MOTION_READBACK_UNAVAILABLE', {'intent': intent}, None)
        assert capsys.readouterr().out == ''

    asyncio.run(run())
