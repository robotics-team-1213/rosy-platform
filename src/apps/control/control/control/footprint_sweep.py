"""Continuous finite-command bounds for a trusted convex chassis footprint.

The caller owns scan coverage, TF, source freshness, geometry provenance and
actuation. A convex hull encloses every supplied chassis vertex; it never
infers a smaller chassis from free laser returns.
"""
import math
from numbers import Real

import numpy as np


def _number(value):
    return isinstance(value,Real) and not isinstance(value,bool) and math.isfinite(value)


def _points(values):
    points=np.asarray(values)
    if (points.ndim!=2 or points.shape[1]!=2 or len(points)<3 or
            points.dtype.kind not in 'fiu' or not np.isfinite(points).all()):
        raise ValueError('Invalid planar points')
    return points.astype(float)


def _hull(points):
    ordered=sorted(set(map(tuple,points)))
    def cross(a,b,c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lower=[]
    upper=[]
    for point in ordered:
        while len(lower)>1 and cross(lower[-2],lower[-1],point)<=0:
            lower.pop()
        lower.append(point)
    for point in reversed(ordered):
        while len(upper)>1 and cross(upper[-2],upper[-1],point)<=0:
            upper.pop()
        upper.append(point)
    hull=np.asarray(lower[:-1]+upper[:-1],dtype=float)
    if len(hull)<3:
        raise ValueError('Degenerate footprint')
    return hull


def _clearance(points, polygon):
    edges=np.roll(polygon,-1,axis=0)-polygon
    delta=points[:,None,:]-polygon[None,:,:]
    inside=np.all(edges[None,:,0]*delta[:,:,1]-edges[None,:,1]*delta[:,:,0]>=0,axis=1)
    fraction=np.clip(np.sum(delta*edges,axis=2)/np.sum(edges*edges,axis=1),0.,1.)
    residual=delta-fraction[:,:,None]*edges
    distance=np.sqrt(np.min(np.sum(residual*residual,axis=2),axis=1))
    return float(np.min(np.where(inside,-distance,distance)))


def _stacked_clearances(points, polygons):
    """_clearance for each polygon of a (T,K,2) stack, with the same per-element arithmetic."""
    edges=np.roll(polygons,-1,axis=1)-polygons
    delta=points[None,:,None,:]-polygons[:,None,:,:]
    inside=np.all(edges[:,None,:,0]*delta[...,1]-edges[:,None,:,1]*delta[...,0]>=0,axis=2)
    fraction=np.clip(np.sum(delta*edges[:,None],axis=3)/np.sum(edges*edges,axis=2)[:,None],0.,1.)
    residual=delta-fraction[...,None]*edges[:,None]
    distance=np.sqrt(np.min(np.sum(residual*residual,axis=3),axis=2))
    return [float(value) for value in np.min(np.where(inside,-distance,distance),axis=1)]


def _clearances(points, polygons):
    """[_clearance(points, p) for p in polygons], skipping provably farther points.

    A point p is left out of polygon t only when its disk bound
    gap=|p-c|-R (c = vertex mean, R = farthest vertex from c) exceeds
    max(U,0)+1e-6, where U is the exact clearance of some kept point, so
    U >= the sample minimum. Every point of the convex polygon lies within R of
    c, hence the true distance D >= gap. The guard below keeps coordinates
    <= 1e3, edges >= 1e-6 and c at least 1e-3*R inside every edge line, so no
    value overflows or divides by zero, rounding moves gap and the computed
    distance by < 1e-10, and the edge line crossed by the segment c->p is at
    least D*1e-3 from p, which makes the computed inside test false. A left-out
    point's computed value therefore exceeds U and cannot be the minimum. The
    minimum's sign of zero can differ; callers only subtract a positive margin
    or compare it.

    Few kept points go through one stacked broadcast; many go polygon by
    polygon through the unchanged _clearance, since a large stack is slower
    than the loop. Both use the original per-element arithmetic.
    """
    polygons=np.asarray(polygons)
    if len(points)>=64:
        centers=polygons.mean(axis=1)
        spokes=polygons-centers[:,None]
        edges=np.roll(polygons,-1,axis=1)-polygons
        lengths=np.sqrt(np.sum(edges*edges,axis=2))
        reach=np.sqrt(np.max(np.sum(spokes*spokes,axis=2),axis=1))
        inner=np.min((edges[...,1]*spokes[...,0]-edges[...,0]*spokes[...,1])/lengths,axis=1)
        scale=max(float(np.max(np.abs(points))),float(np.max(np.abs(polygons))))
        with np.errstate(all='ignore'):
            usable=bool(scale<=1e3 and np.min(lengths)>=1e-6 and np.all(inner>=1e-3*reach))
        if usable:
            offset=points[None]-centers[:,None]
            gaps=np.sqrt(np.sum(offset*offset,axis=2))-reach[:,None]
            best=np.argmin(gaps,axis=1)
            chosen=np.unique(best)
            bounds=_stacked_clearances(points[chosen],polygons)
            keep=gaps<=np.maximum(bounds,0.)[:,None]+1e-6
            keep[np.arange(len(polygons)),best]=True
            union=np.any(keep,axis=0)
            if int(np.count_nonzero(union))*len(polygons)<=4096:
                return _stacked_clearances(points[union],polygons)
            return [_clearance(points[mask],polygon) for polygon,mask in zip(polygons,keep)]
    return [_clearance(points,polygon) for polygon in polygons]


def _travel_candidates(obstacles, hull, margin, maximum):
    """Obstacles that can decide `clearance > margin` for any hull swept up to `maximum`.

    Only that comparison leaves footprint_translation_limits, so a point whose
    computed clearance exceeds margin can be dropped. With c the hull vertex
    mean, R its farthest vertex and r its smallest edge-line distance, every
    swept hull contains the disk (c,r) and lies in the disk (c,R+maximum), so
    the true distance D >= |p-c|-(R+maximum) and the edge line crossed by the
    segment c->p is at least D*r/(R+maximum) from p. The guard (coordinates
    <= 1e3, hull edges >= 1e-6, maximum >= 1e-6, r >= 1e-3*(R+maximum)) keeps
    that line >= 1e-5 away for D > margin >= .01, far beyond rounding, so a
    dropped point is computed outside at a distance > margin. The best-bound
    point is always kept so the set is never empty.
    """
    if len(obstacles)<64 or maximum<1e-6:
        return obstacles
    center=hull.mean(axis=0)
    spokes=hull-center
    edges=np.roll(hull,-1,axis=0)-hull
    lengths=np.sqrt(np.sum(edges*edges,axis=1))
    reach=float(np.sqrt(np.max(np.sum(spokes*spokes,axis=1))))+maximum
    inner=float(np.min((edges[:,1]*spokes[:,0]-edges[:,0]*spokes[:,1])/lengths))
    scale=max(float(np.max(np.abs(obstacles))),float(np.max(np.abs(hull)))+maximum)
    if not (scale<=1e3 and float(np.min(lengths))>=1e-6 and inner>=1e-3*reach):
        return obstacles
    offset=obstacles-center
    gap=np.sqrt(np.sum(offset*offset,axis=1))-reach
    keep=gap<=margin+1e-6
    keep[np.argmin(gap)]=True
    return obstacles[keep]


def _geometry(points, footprint, center, uncertainty, body_radius, scan_age):
    cx,cy=center
    if (not all(_number(v) for v in (cx,cy,uncertainty,body_radius,scan_age)) or
            not 0<=uncertainty<=.03 or body_radius<=0 or not 0<=scan_age<=.2):
        raise ValueError('Invalid geometry or observation')
    obstacles=_points(points)
    hull=_hull(_points(footprint))
    # Only the complete trusted geometry can replace its enclosing circle.
    if abs(float(np.max(np.linalg.norm(hull,axis=1)))-body_radius)>1e-6:
        raise ValueError('Footprint does not match body radius')
    pivot_radius=float(np.max(np.linalg.norm(hull-np.array(center),axis=1)))
    # Unlike a body circle, a polygon changes orientation during observation
    # delay and old-command settling. Bound every vertex, not just base_link.
    padding=(.014+.10*(pivot_radius+2*uncertainty))*(scan_age+.15)
    return obstacles,hull,pivot_radius,.010+2*uncertainty+padding


def footprint_sweep_clearance(points, footprint, center, uncertainty, body_radius,
                              v, w, horizon, scan_age):
    """Signed continuous swept clearance; None means no valid evidence."""
    try:
        if (not all(_number(x) for x in (v,w,horizon)) or abs(v)>.014 or
                abs(w)>.1 or not .75<=horizon<=1.5):
            return None
        obstacles,hull,pivot_radius,margin=_geometry(
            points,footprint,center,uncertainty,body_radius,scan_age)
        cx,cy=center
        intervals=math.ceil(horizon/.05)
        # Every vertex moves at most this fast; the nearest time sample is
        # <=dt/2 away. Minkowski dilation covers all intermediate polygons.
        margin+=(abs(v)+abs(w)*pivot_radius)*horizon/intervals/2
        polygons=[]
        for index in range(intervals+1):
            t=horizon*index/intervals
            angle=w*t
            sine=math.sin(angle)
            one_minus_cosine=2*math.sin(angle/2)**2
            cosine=1-one_minus_cosine
            sinc=sine/angle if angle else 1.
            cosc=one_minus_cosine/angle if angle else 0.
            shift=np.array([one_minus_cosine*cx+sine*cy+v*t*sinc,
                            -sine*cx+one_minus_cosine*cy+v*t*cosc])
            polygons.append(hull@np.array([[cosine,sine],[-sine,cosine]])+shift)
        nearest=math.inf
        for value in _clearances(obstacles,polygons):
            nearest=min(nearest,value)
        result=nearest-margin
        return result if math.isfinite(result) else None
    except (TypeError,ValueError,OverflowError):
        return None


def footprint_translation_limits(points, footprint, center, uncertainty, body_radius, scan_age, maximum=.03):
    """Safe observed straight travel, capped at 3 cm; no motor authority."""
    try:
        if not _number(maximum) or not 0<maximum<=.12:return None
        obstacles,hull,_,margin=_geometry(points,footprint,center,uncertainty,body_radius,scan_age)
        obstacles=_travel_candidates(obstacles,hull,margin,maximum)
        if _clearance(obstacles,hull)<=margin:
            return (0.,0.)
        limits=[]
        for sign in (1.,-1.):
            def clear(distance):
                # Convex polygon + translation segment is exactly this hull.
                swept=_hull(np.vstack((hull,hull+np.array([sign*distance,0.]))))
                return _clearance(obstacles,swept)>margin
            if clear(maximum):
                limits.append(maximum)
                continue
            low,high=0.,maximum
            for _ in range(10):
                middle=(low+high)/2
                if clear(middle):low=middle
                else:high=middle
            limits.append(max(0.,low-.0001))
        return tuple(limits)
    except (TypeError,ValueError,OverflowError):
        return None
