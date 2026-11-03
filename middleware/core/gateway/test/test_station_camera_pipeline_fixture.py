"""The synthetic camera pipeline stays inside its OpenCV thread budget."""
import pytest

from test_station_camera_pipeline import pipeline_sources


@pytest.mark.parametrize('body_fails', [False, True])
def test_pipeline_limits_opencv_threads_and_restores_them(monkeypatch, body_fails):
    cv2 = pytest.importorskip('cv2')
    threads = [24]
    monkeypatch.setattr(cv2, 'getNumThreads', lambda: threads[0])
    monkeypatch.setattr(cv2, 'setNumThreads', lambda value: threads.__setitem__(0, value))

    class BodyFailure(Exception):
        pass

    def exercise():
        setup = pipeline_sources.__wrapped__(monkeypatch)
        if setup is not None:
            next(setup)
        try:
            assert threads[0] == 1
            if body_fails:
                raise BodyFailure
        finally:
            if setup is not None:
                setup.close()

    if body_fails:
        with pytest.raises(BodyFailure):
            exercise()
    else:
        exercise()
    assert threads[0] == 24
