"""D-185 R5: the optimised footprint sweep must reproduce the original bit for bit.

The sim safety node calls footprint_sweep_clearance (17 time samples x every scan point
x hull edge) and footprint_translation_limits (up to 2 x 10 bisection steps) on every
20 Hz tick; the original cost 12 ms (720 points) to 31 ms (1440 points) per sweep call on
an idle x86 core (2026-09-24). Every returned value is compared by repr(), so float bits,
-0.0 and None are checked, and every value must be a builtin float/tuple/None (the
original returns np.float64 only for a numpy-scalar command argument; that type is kept).
"""
import math
import random
from numbers import Real

import numpy as np
import pytest

import control.control.footprint_sweep as fs


# Huge-scale cases overflow on purpose in both implementations.
pytestmark=pytest.mark.filterwarnings('ignore::RuntimeWarning')


# --- Verbatim copy of control/control/footprint_sweep.py before optimisation (main 89001aad) ---

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
        nearest=math.inf
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
            polygon=hull@np.array([[cosine,sine],[-sine,cosine]])+shift
            nearest=min(nearest,_clearance(obstacles,polygon))
        result=nearest-margin
        return result if math.isfinite(result) else None
    except (TypeError,ValueError,OverflowError):
        return None


def footprint_translation_limits(points, footprint, center, uncertainty, body_radius, scan_age, maximum=.03):
    """Safe observed straight travel, capped at 3 cm; no motor authority."""
    try:
        if not _number(maximum) or not 0<maximum<=.12:return None
        obstacles,hull,_,margin=_geometry(points,footprint,center,uncertainty,body_radius,scan_age)
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

# --- End of verbatim copy ---


PINKY_RADIUS=.086


def octagon(radius=PINKY_RADIUS, phase=math.pi/8):
    return [(radius*math.cos(phase+k*math.pi/4),radius*math.sin(phase+k*math.pi/4)) for k in range(8)]


def random_footprint(rng):
    kind=rng.random()
    if kind<.25:
        shape=octagon(rng.choice((PINKY_RADIUS,rng.uniform(.03,.2))),rng.choice((math.pi/8,0.,rng.uniform(0,1))))
    elif kind<.55:  # convex: points on a circle, possibly irregular
        n=rng.randint(3,16)
        radius=rng.uniform(.02,.25)
        angles=sorted(rng.uniform(0,2*math.pi) for _ in range(n))
        shape=[(radius*math.cos(a),radius*math.sin(a)) for a in angles]
    elif kind<.85:  # non-convex star; the hull must enclose every vertex
        n=rng.randint(3,16)
        base=rng.uniform(.03,.2)
        shape=[(base*rng.uniform(.3,1.)*math.cos(2*math.pi*k/n),
                base*rng.uniform(.3,1.)*math.sin(2*math.pi*k/n)) for k in range(n)]
    else:  # boxes and slivers, duplicates, reversed order, int grids
        a,b=rng.uniform(.01,.12),rng.uniform(.002,.08)
        shape=[(-a,-b),(a,-b),(a,b),(-a,b)]
        if rng.random()<.3:
            shape=shape+shape[::-1]
        if rng.random()<.2:
            shape=[(-2,-1),(2,-1),(2,1),(-2,1),(0,0)]
    shape=[(x+rng.choice((0.,rng.uniform(-.03,.03))),y) for x,y in shape] if rng.random()<.2 else shape
    rng.shuffle(shape)
    return shape


def scaled(shape, scale):
    return [(x*scale,y*scale) for x,y in shape]


def body_radius_of(footprint):
    try:
        return float(np.max(np.linalg.norm(_hull(_points(footprint)),axis=1)))
    except ValueError:
        return .1


def random_points(rng, count, footprint, scale=1.):
    hull=_hull(_points(footprint)) if len(footprint)>=3 else np.zeros((1,2))
    reach=float(np.max(np.linalg.norm(hull,axis=1))) if hull.size else .1
    # Most scans keep every return outside the circumscribed circle; a quarter reach inside.
    nearest=rng.choice((0.,reach*1.001,reach+.02,reach+.05,reach+.15))
    points=[]
    style=rng.random()
    for index in range(count):
        roll=rng.random()
        if style<.4:  # laser ring: evenly spaced bearings, ranges from contact to far walls
            angle=2*math.pi*index/count
            distance=rng.choice((rng.uniform(nearest,reach*1.5+nearest),rng.uniform(reach,reach+.3),
                                 rng.uniform(.3,3.5)))
            distance=max(distance,nearest)
            points.append((distance*math.cos(angle),distance*math.sin(angle)))
        elif roll<.02 and not nearest:  # inside the hull
            vertex=hull[rng.randrange(len(hull))]
            t=rng.random()
            points.append((float(vertex[0]*t),float(vertex[1]*t)))
        elif roll<.2:  # just around the boundary
            vertex=hull[rng.randrange(len(hull))]
            t=rng.uniform(.95,1.2)
            if nearest:
                t=max(t,nearest/max(float(np.hypot(*vertex)),1e-300))
            points.append((float(vertex[0]*t),float(vertex[1]*t)))
        else:
            distance=rng.choice((rng.uniform(0,.5),rng.uniform(.2,4.),rng.uniform(3,20)))*scale/max(scale,1.)
            distance=max(distance,nearest)
            angle=rng.uniform(0,2*math.pi)
            points.append((distance*math.cos(angle),distance*math.sin(angle)))
    if scale!=1.:
        points=[(x*scale,y*scale) for x,y in points]
    return points


def corridor_points(rng, count, footprint):
    """Walls ahead of and behind the hull at gaps around the travel cap plus margin."""
    hull=_hull(_points(footprint))
    front,back=float(np.max(hull[:,0])),float(np.min(hull[:,0]))
    ahead,behind=front+rng.uniform(0,.2),back-rng.uniform(0,.2)
    side=float(np.max(np.abs(hull[:,1])))+rng.uniform(.03,.5)
    points=[]
    for index in range(count):
        roll=rng.random()
        y=rng.uniform(-side,side)
        if roll<.35:
            points.append((ahead+rng.uniform(0,.05),y))
        elif roll<.7:
            points.append((behind-rng.uniform(0,.05),y))
        else:
            points.append((rng.uniform(behind-.3,ahead+.3),rng.choice((-1,1))*(side+rng.uniform(0,.5))))
    return points


def random_case(rng):
    scale=rng.choice((1.,)*20+(1e-3,1e3,1e100,1e154,1e155,1e160,1e-150))
    footprint=scaled(random_footprint(rng),scale)
    radius=body_radius_of(footprint)
    radius=rng.choice((radius,)*30+(radius+5e-7,radius-5e-7,radius+2e-6,radius*1.5,-radius))
    size=rng.choice((rng.randint(3,40),rng.randint(3,40),rng.randint(40,300),rng.randint(300,1500)))
    points=random_points(rng,size,footprint,scale if scale>1e10 or scale<1e-10 else 1.)
    if rng.random()<.1:
        points=np.asarray(points)
    extent=radius if math.isfinite(radius) and radius>0 else .1
    center=rng.choice(((0.,0.),(0.,0.),(rng.uniform(-.5,.5)*extent,rng.uniform(-.5,.5)*extent),
                       (rng.uniform(-2,2)*extent,0.),(0,0)))
    uncertainty=rng.choice((0.,0.,.03,rng.uniform(0,.03),rng.uniform(0,.004))*4+(.030000001,-1e-12))
    scan_age=rng.choice((0.,.2,rng.uniform(0,.2),.1)*4+(.2000001,-1e-9))
    return dict(points=points,footprint=footprint,center=center,uncertainty=uncertainty,
                body_radius=radius,scan_age=scan_age)


def command(rng):
    v=rng.choice((0.,.014,-.014,rng.uniform(-.014,.014),rng.uniform(-.014,.014),-0.,1e-300)*3+
                 (rng.uniform(-.02,.02),.0140001))
    w=rng.choice((0.,.1,-.1,rng.uniform(-.1,.1),rng.uniform(-.1,.1),1e-12,-1e-12,-0.)*3+
                 (rng.uniform(-.15,.15),.1000001))
    horizon=rng.choice((.75,1.5,.8,1.,rng.uniform(.75,1.5),.75+1e-12,1.4999999999,.05*16,.05*17,1.05)*3+
                       (rng.uniform(.7,1.6),.7499999999,1.5000000001))
    return v,w,horizon


INVALID=[
    ('points', [[0.,0.],[1.,1.]]),
    ('points', [[0.,0.,0.],[1.,1.,1.],[2.,2.,2.]]),
    ('points', [1.,2.,3.]),
    ('points', [[float('nan'),0.],[1.,1.],[2.,2.]]),
    ('points', [[float('inf'),0.],[1.,1.],[2.,2.]]),
    ('points', np.array([[True,False],[False,True],[True,True]])),
    ('points', [['a','b'],['c','d'],['e','f']]),
    ('points', None),
    ('points', [[.3,.0],[.3,.1],[.3,.2]]*0),
    ('footprint', [[0,0],[.01,0],[.02,0]]),
    ('footprint', [[0,0],[0,0],[0,0]]),
    ('footprint', [[0,0],[1,1]]),
    ('footprint', [[float('nan'),0],[1,1],[1,0]]),
    ('center', (float('nan'),0.)),
    ('center', (True,0.)),
    ('center', (0.,0.,0.)),
    ('center', 5.),
    ('center', None),
    ('uncertainty', True),
    ('uncertainty', float('inf')),
    ('uncertainty', '0'),
    ('body_radius', False),
    ('body_radius', float('nan')),
    ('body_radius', 0.),
    ('scan_age', float('nan')),
    ('scan_age', True),
]

INVALID_COMMAND=[
    ('v', True), ('v', float('nan')), ('v', float('inf')), ('v', '0'), ('v', None), ('v', 1+0j),
    ('w', False), ('w', float('-inf')), ('horizon', True), ('horizon', float('nan')), ('horizon', np.float64(.8)),
    ('v', np.float32(.01)), ('w', np.int64(0)), ('horizon', 1),
]


def check_same(new, old, where, builtin=True):
    assert repr(new)==repr(old), where
    if old is None:
        assert new is None, where
    elif isinstance(old,tuple):
        assert type(new) is tuple and len(new)==2 and all(type(v) is float for v in new), where
    else:
        # The original returns a numpy scalar when a command argument is a numpy scalar
        # (np.float64 horizon); that type is part of the result and is kept.
        assert type(new) is type(old), where
        if builtin:
            assert type(new) is float, where


def sweep_class(case, v, w, horizon, result):
    if not (all(_number(x) for x in (v,w,horizon)) and abs(v)<=.014 and abs(w)<=.1 and .75<=horizon<=1.5):
        return 'invalid_command'
    try:
        obstacles,hull,_,_=_geometry(case['points'],case['footprint'],case['center'],
                                     case['uncertainty'],case['body_radius'],case['scan_age'])
    except (TypeError,ValueError,OverflowError):
        return 'invalid_geometry'
    if result is None:
        return 'nonfinite'
    if _clearance(obstacles,hull)<0:
        return 'inside_hull'
    return 'collision' if result<0 else 'clear'


def translation_class(case, maximum, result):
    if result is None:
        return 'invalid'
    if result==(0.,0.):
        return 'stopped'
    classes=set()
    for limit in result:
        classes.add('full' if limit==maximum else 'bisect')
    return '+'.join(sorted(classes))


def test_sweep_matches_the_original_bit_for_bit():
    rng=random.Random(18505)
    seen={}
    for index in range(900):
        case=random_case(rng)
        v,w,horizon=command(rng)
        if index%15==0:
            name,value=rng.choice(INVALID_COMMAND)
            v,w,horizon={'v':(value,w,horizon),'w':(v,value,horizon),'horizon':(v,w,value)}[name]
        elif index%11==0:
            name,value=rng.choice(INVALID)
            case=dict(case,**{name:value})
        old=footprint_sweep_clearance(v=v,w=w,horizon=horizon,**case)
        new=fs.footprint_sweep_clearance(v=v,w=w,horizon=horizon,**case)
        check_same(new,old,(index,v,w,horizon),builtin=all(type(x) in (int,float) for x in (v,w,horizon)))
        kind=sweep_class(case,v,w,horizon,old)
        seen[kind]=seen.get(kind,0)+1
    assert set(seen)=={'invalid_command','invalid_geometry','nonfinite','inside_hull','collision','clear'}, seen
    assert min(seen.values())>=5, seen


def test_translation_limits_match_the_original_bit_for_bit():
    rng=random.Random(18506)
    seen={}
    for index in range(500):
        case=random_case(rng)
        if rng.random()<.5 and isinstance(case['points'],list):
            case['points']=corridor_points(rng,len(case['points']),case['footprint'])
        maximum=rng.choice((.03,.03,.12,rng.uniform(.001,.12),.005)*4+(.12000001,0.,True,float('nan'),-.01,1))
        if index%11==0:
            name,value=rng.choice(INVALID)
            case=dict(case,**{name:value})
        old=footprint_translation_limits(maximum=maximum,**case)
        new=fs.footprint_translation_limits(maximum=maximum,**case)
        check_same(new,old,(index,maximum))
        kind=translation_class(case,maximum,old)
        seen[kind]=seen.get(kind,0)+1
    assert {'invalid','stopped','full','bisect','bisect+full'}<=set(seen), seen
    assert min(seen.values())>=5, seen


def test_pinky_octagon_scans_match_across_the_whole_command_domain():
    rng=random.Random(18507)
    footprint=octagon()
    radius=body_radius_of(footprint)
    for count in (360,720,1440):
        for _ in range(3):
            ranges=[rng.choice((rng.uniform(.09,.4),rng.uniform(.3,3.5))) for _ in range(count)]
            points=[(r*math.cos(2*math.pi*i/count),r*math.sin(2*math.pi*i/count)) for i,r in enumerate(ranges)]
            case=dict(points=points,footprint=footprint,center=(rng.uniform(-.01,.01),0.),
                      uncertainty=rng.uniform(0,.003),body_radius=radius,scan_age=rng.uniform(0,.2))
            for v,w in ((0.,0.),(.014,.1),(-.014,-.1),(.01,-.05),(0.,.1),(-0.,-0.)):
                for horizon in (.75,.8,1.5):
                    check_same(fs.footprint_sweep_clearance(v=v,w=w,horizon=horizon,**case),
                               footprint_sweep_clearance(v=v,w=w,horizon=horizon,**case),(count,v,w,horizon))
            for maximum in (.03,.12):
                check_same(fs.footprint_translation_limits(maximum=maximum,**case),
                           footprint_translation_limits(maximum=maximum,**case),(count,maximum))


def test_straight_escape_helpers_keep_their_original_values():
    rng=random.Random(18508)
    for _ in range(200):
        footprint=random_footprint(rng)
        points=np.asarray(random_points(rng,rng.randint(3,300),footprint))
        assert repr(fs._hull(np.asarray(footprint,dtype=float)).tolist())==repr(_hull(np.asarray(footprint,dtype=float)).tolist())
        hull=_hull(np.asarray(footprint,dtype=float))
        value=fs._clearance(points,hull)
        assert type(value) is float and repr(value)==repr(_clearance(points,hull))


def test_translation_limits_with_obstacles_on_the_travel_axis_match():
    # The candidate filter's disk bound is tight on the travel axis: a point just inside
    # maximum+margin of the leading vertex decides the limit and must never be dropped.
    rng=random.Random(18509)
    decided=0
    for index in range(160):
        footprint=octagon(PINKY_RADIUS,0.) if index%2 else random_footprint(rng)
        radius=body_radius_of(footprint)
        hull=_hull(_points(footprint))
        maximum=rng.choice((.03,.12,rng.uniform(.001,.12)))
        case=dict(footprint=footprint,center=(0.,0.),uncertainty=rng.choice((0.,.002)),
                  body_radius=radius,scan_age=rng.choice((0.,.1)))
        margin=_geometry([(1.,1.),(2.,2.),(3.,1.)],**case)[3]
        points=[(3.*math.cos(a),3.*math.sin(a)) for a in np.linspace(0,2*math.pi,rng.randint(64,200),endpoint=False)]
        sign=rng.choice((1.,-1.))
        lead=hull[np.argmax(sign*hull[:,0])]
        for _ in range(rng.randint(1,4)):
            reach=maximum+margin+rng.uniform(-6e-3,1e-3)
            points.append((float(lead[0])+sign*reach,float(lead[1])+rng.uniform(-1e-3,1e-3)))
        # A side point where the disk bound is loose by the travel: smaller bound, no block.
        side=float(np.max(hull[:,1]))+margin+maximum*.6
        points.append((float(hull[np.argmax(hull[:,1]),0]),side))
        rng.shuffle(points)
        old=footprint_translation_limits(points,maximum=maximum,**case)
        new=fs.footprint_translation_limits(points,maximum=maximum,**case)
        check_same(new,old,(index,maximum))
        decided+=old is not None and old[int(sign<0)]<maximum
    assert decided>=40, decided


def same_value(new, old):
    # Internal sample minima may differ only in the sign of a zero (see _clearances).
    return type(new) is float and (repr(new)==repr(old) or new==old==0.)


def traced_clearances(monkeypatch, points, polygons):
    """fs._clearances with the path taken: fallback, stacked or per_sample, and whether points were dropped."""
    stacked,single=[],[]
    original_stacked,original_single=fs._stacked_clearances,fs._clearance
    monkeypatch.setattr(fs,'_stacked_clearances',lambda p,q:(stacked.append(len(p)),original_stacked(p,q))[1])
    monkeypatch.setattr(fs,'_clearance',lambda p,q:(single.append(len(p)),original_single(p,q))[1])
    try:
        values=fs._clearances(points,polygons)
    finally:
        monkeypatch.setattr(fs,'_stacked_clearances',original_stacked)
        monkeypatch.setattr(fs,'_clearance',original_single)
    if not stacked:
        return values,'fallback',False
    if len(stacked)==2:
        return values,'stacked',stacked[1]<len(points)
    return values,'per_sample',any(n<len(points) for n in single)


def near_guard_polygons(rng):
    # Coordinates near 1e3, 1e-6 edges and slivers whose inner distance is near 1e-3*R.
    count=int(rng.choice([3,4,6,12]))
    radius=float(rng.choice([1.,100.,400.,499.]))
    angles=np.sort(rng.uniform(0,2*np.pi,count))
    shape=np.c_[np.cos(angles),np.sin(angles)]*radius
    if rng.random()<.5:
        index=rng.integers(count)
        step=float(rng.choice([1e-6,1.0000001e-6,3e-6]))
        turn=rng.uniform(0,2*np.pi)
        shape=np.vstack([shape,shape[index]+step*np.array([np.cos(turn),np.sin(turn)])])
    if rng.random()<.5:
        shape[:,1]*=float(rng.choice([1.2e-3,2e-3,2.002e-3]))
    shape=shape+rng.uniform(-1,1,2)*(999-radius)*rng.random()
    hull=_hull(shape)
    samples=int(rng.choice([1,3,17,40]))
    polygons=[]
    for index in range(samples):
        turn=rng.uniform(-.15,.15)*(index>0)
        c,s=math.cos(turn),math.sin(turn)
        polygons.append(hull@np.array([[c,s],[-s,c]])+rng.uniform(-.01,.01,2)*(index>0))
    return np.asarray(polygons)


def near_guard_points(rng, polygons):
    center=polygons[0].mean(0)
    reach=float(np.sqrt(((polygons[0]-center)**2).sum(1)).max())
    # The exact bound of a near point sets U; points then sit at the drop threshold.
    near=polygons[0][0]+(polygons[0][0]-center)/reach*float(rng.choice([1e-3,.05,.5]))
    bound=_clearance(near[None],polygons[0])
    points=[near]
    for _ in range(int(rng.choice([64,100,300]))):
        polygon=polygons[rng.integers(len(polygons))]
        edge=rng.integers(len(polygon))
        a,b=polygon[edge],polygon[(edge+1)%len(polygon)]
        mode=rng.random()
        if mode<.3:
            normal=np.array([b[1]-a[1],a[0]-b[0]])
            normal/=np.linalg.norm(normal)
            points.append(a+rng.random()*(b-a)+float(rng.choice([0.,1e-7,1e-6,2e-6,5e-6]))*normal)
        elif mode<.7:
            direction=(a-center)/np.linalg.norm(a-center)
            step=float(rng.choice([1e-6,1.5e-6,2e-6,1e-5,1e-3]))
            points.append(center+direction*(reach+max(bound,0.)+step))
        else:
            normal=np.array([b[1]-a[1],a[0]-b[0]])
            normal/=np.linalg.norm(normal)
            points.append(a+rng.random()*(b-a)+rng.uniform(0,5)*normal)
    return np.clip(np.asarray(points),-1e3,1e3)


def test_sample_minima_match_near_the_prefilter_guard(monkeypatch):
    rng=np.random.default_rng(18510)
    paths={}
    for index in range(400):
        try:
            polygons=near_guard_polygons(rng)
        except ValueError:
            continue
        if np.max(np.abs(polygons))>1e3:
            continue
        points=near_guard_points(rng,polygons)
        values,path,dropped=traced_clearances(monkeypatch,points,polygons)
        expected=[_clearance(points,polygon) for polygon in polygons]
        assert len(values)==len(expected) and all(map(same_value,values,expected)), index
        key=(path,dropped)
        paths[key]=paths.get(key,0)+1
    assert paths.get(('stacked',True),0)>=5 and paths.get(('per_sample',True),0)>=5, paths
    assert paths.get(('fallback',False),0)>=5, paths


def test_translation_limits_match_near_the_candidate_guard():
    rng=np.random.default_rng(18511)
    cases=0
    for index in range(240):
        count=int(rng.choice([3,4,8,12]))
        radius=float(rng.choice([.086,1.,50.,500.,998.]))
        angles=np.sort(rng.uniform(0,2*np.pi,count))
        shape=np.c_[np.cos(angles),np.sin(angles)]*radius
        if rng.random()<.4:
            vertex=rng.integers(count)
            turn=rng.uniform(0,2*np.pi)
            shape=np.vstack([shape,shape[vertex]*(1-3e-6/radius)+1e-6*np.array([np.cos(turn),np.sin(turn)])])
        if rng.random()<.4:
            shape[:,1]*=float(rng.choice([.05,.2]))
        try:
            hull=_hull(shape)
        except ValueError:
            continue
        maximum=float(rng.choice([1e-3,1e-3*(1+1e-12),1e-3*(1-1e-12),9.99e-4,1.001e-3,1e-6,.03,.12]))
        case=dict(footprint=shape.tolist(),center=(0.,0.),uncertainty=float(rng.choice([0.,.03])),
                  body_radius=float(np.max(np.linalg.norm(hull,axis=1))),scan_age=float(rng.choice([0.,.2])))
        margin=_geometry([(1,1),(2,2),(3,1)],**case)[3]
        points=[]
        for _ in range(int(rng.choice([64,120,400]))):
            shift=rng.uniform(0,maximum)*rng.choice([1,-1])
            swept=_hull(np.vstack([hull,hull+[shift,0]]))
            edge=rng.integers(len(swept))
            a,b=swept[edge],swept[(edge+1)%len(swept)]
            normal=np.array([b[1]-a[1],a[0]-b[0]])
            normal/=np.linalg.norm(normal)
            offset=margin+float(rng.choice([0.,1e-12,-1e-12,1e-9,1e-7,1e-6,2e-6,-1e-6,rng.uniform(-.01,.05)]))
            points.append(a+rng.random()*(b-a)+offset*normal)
        points=np.clip(np.asarray(points),-1e3,1e3).tolist()
        check_same(fs.footprint_translation_limits(points,maximum=maximum,**case),
                   footprint_translation_limits(points,maximum=maximum,**case),(index,radius,maximum))
        cases+=1
    assert cases>=150, cases
