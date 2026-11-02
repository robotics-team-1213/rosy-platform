"""The batched/per-axis scan registration must reproduce the original exactly (D-953).

match_motion was 73 ms per call on a Pi 5 (D-185 R8) against a 50 ms calibration tick, and a
Pi 4 is about 2.5x slower again. Results must be bit-identical (D-185 rule 2, class E): an
expanded |d|^2-2t(d.e)+t^2|e|^2 distance looked equal on synthetic rooms but flipped
shared-vertex ties on the recorded frames below and rejected them.
"""
import gzip
import json
import math
from pathlib import Path

import numpy as np
import pytest

import control.sensing.scan_motion as sm
from tools.device import hotpath_measure as hm


def reference_segments(ref):
    """Verbatim copy of scan_motion._segments before D-953 (main 875975bf)."""
    edges = np.diff(ref,axis=0)
    lengths = np.linalg.norm(edges,axis=1)
    directions = edges/np.maximum(lengths[:,None],1e-12)
    aligned = np.sum(directions[1:]*directions[:-1],axis=1) > .995
    supported = np.r_[False,aligned] | np.r_[aligned,False]
    for start in range(len(ref)-3):
        if np.any(lengths[start:start+3] >= .08):
            continue
        window=ref[start:start+4]
        centered=window-window.mean(axis=0)
        _,_,axes=np.linalg.svd(centered,full_matrices=False)
        extent=np.ptp(centered@axes[0])
        if extent >= .01 and np.max(np.abs(centered@axes[1])) <= .001:
            supported[start:start+3]=True
    keep = (lengths > .0001) & (lengths < .08) & supported
    if keep.sum() < max(20,.4*len(ref)):
        return None
    return ref[:-1][keep],edges[keep],lengths[keep]**2


def reference_fit_segments(segments,cur,hint,initial=None):
    """Verbatim copy of scan_motion._fit_segments before D-953 (main 875975bf)."""
    starts,edges,length2 = segments
    normals = np.column_stack((-edges[:,1],edges[:,0]))/np.sqrt(length2[:,None])
    rotation,translation = sm._rotation(hint),np.zeros(2)
    if initial is not None:
        rotation,translation=initial[0].copy(),initial[1].copy()
    def correspondence(aligned):
        offsets=aligned[:,None,:]-starts[None,:,:]
        fractions=np.sum(offsets*edges[None,:,:],axis=2)/length2
        projections=starts[None,:,:]+np.clip(fractions,0.,1.)[:,:,None]*edges[None,:,:]
        distance2=np.sum((aligned[:,None,:]-projections)**2,axis=2)
        closest=np.argmin(distance2,axis=1)
        errors=np.sqrt(distance2[np.arange(len(cur)),closest])
        interior=(fractions[np.arange(len(cur)),closest]>=-1e-12)&(fractions[np.arange(len(cur)),closest]<=1.+1e-12)
        keep=interior&(errors<=min(.04,max(.002,float(np.quantile(errors,.8)))))
        return closest,errors,keep
    for _ in range(14):
        aligned=cur@rotation.T+translation
        closest,errors,keep=correspondence(aligned)
        if keep.sum()<max(20,.6*len(cur)):
            return None
        p=aligned[keep]
        n=normals[closest[keep]]
        residual=np.sum(n*(p-starts[closest[keep]]),axis=1)
        jacobian=np.column_stack((n,np.sum(n*np.column_stack((-p[:,1],p[:,0])),axis=1)))
        scale=max(.05,float(np.sqrt(np.mean(np.sum(p*p,axis=1)))))
        singular=np.linalg.svd(jacobian/np.array([1.,1.,scale]),compute_uv=False)
        if singular[-1]<.025*singular[0]:
            return None
        update=np.linalg.lstsq(jacobian,-residual,rcond=None)[0]
        if np.linalg.norm(update[:2])>.06 or abs(update[2])>.2:
            return None
        incremental=sm._rotation(float(update[2]))
        rotation=incremental@rotation
        translation=incremental@translation+update[:2]
        if np.linalg.norm(update)<1e-7:
            break
    _,errors,keep=correspondence(cur@rotation.T+translation)
    if keep.sum()<max(20,.6*len(cur)):
        return None
    return rotation,translation,float(np.sqrt(np.mean(errors[keep]**2)))


def moved(points, yaw, dx=0., dy=0.):
    c, s = math.cos(yaw), math.sin(yaw)
    return (points-np.array([dx, dy]))@np.array([[c, -s], [s, c]])


def corpus():
    rng = np.random.default_rng(952)
    with gzip.open(Path(__file__).parent/'fixtures/registration_stationary_endpoints_20260909.json.gz', 'rt') as f:
        frames = [np.array(p) for p in json.load(f)]
    cases = [(hm.box_cloud(), hm.box_cloud(yaw=math.radians(10.)), math.radians(10.))]
    for _ in range(30):
        yaw = math.radians(rng.uniform(-12., 12.))
        cur = moved(hm.box_cloud(), yaw, *rng.uniform(-.02, .02, 2))+rng.normal(0., .0005, (180, 2))
        cases.append((hm.box_cloud()+rng.normal(0., .0005, (180, 2)), cur, yaw+rng.uniform(-.02, .02)))
    for points in frames:
        cases.append((points, points, 0.))
        for yaw in (-math.radians(10.), math.radians(10.)):
            cases.append((points, np.delete(moved(points, yaw, .01, -.005), [4, 19, 47], axis=0), yaw))
        cases.append((points, moved(points, .3), 0.))  # hint far off: rejected
    wall = np.column_stack((np.linspace(-1., 1., 90), np.full(90, .5)))
    corridor = np.r_[wall, wall-[0., 1.]]
    circle = .8*np.column_stack((np.cos(np.linspace(0., 6.2, 120)), np.sin(np.linspace(0., 6.2, 120))))
    cases += [(wall, wall, 0.), (corridor, moved(corridor, .02), .02), (circle, moved(circle, .05), .05),
              (hm.box_cloud()[:20], hm.box_cloud()[:20], 0.)]
    return cases


@pytest.fixture
def reference(monkeypatch):
    def run(*case):
        with monkeypatch.context() as m:
            m.setattr(sm, '_segments', reference_segments)
            m.setattr(sm, '_fit_segments', reference_fit_segments)
            return sm.match_motion(*case)
    return run


def test_segments_are_bit_identical():
    for ref, cur, _ in corpus():
        for points in (np.asarray(ref, float), np.asarray(cur, float)):
            old, new = reference_segments(points), sm._segments(points)
            assert (old is None) == (new is None)
            if old is not None:
                assert all(np.array_equal(a, b) for a, b in zip(old, new))


def test_segments_short_inputs_match():
    for n in range(8):  # below one 4-return window the batch has nothing to stack
        points = np.random.default_rng(n).normal(size=(n, 2))
        assert reference_segments(points) is None and sm._segments(points) is None


def test_match_motion_is_bit_identical(reference):
    accepted = rejected = 0
    for case in corpus():
        old = reference(*case)
        assert sm.match_motion(*case) == old
        accepted, rejected = accepted+(old is not None), rejected+(old is None)
    assert accepted >= 40 and rejected >= 8  # the corpus exercises both outcomes
