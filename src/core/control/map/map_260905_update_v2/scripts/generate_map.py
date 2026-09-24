#!/usr/bin/env python3
"""Convert this box-only Gazebo track into an exact plan and a static map.

This converter is intentionally scoped to map_260905.world. It accepts planar
static boxes with normal SDF parent-relative poses. It rejects relative_to,
non-planar poses, meshes, includes, and unknown collision geometry rather than
silently making an inaccurate map. Plane ground geometry is ignored.
Dependencies: numpy, Pillow, shapely>=2, scipy, PyYAML, cairosvg.
"""
from __future__ import annotations
import argparse
import hashlib
import html
import json
import math
import shutil
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image
from scipy import ndimage
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
import yaml
import cairosvg


def pose_of(element: ET.Element) -> tuple[float, ...]:
    pose = element.find('pose')
    if pose is None:
        return (0., 0., 0., 0., 0., 0.)
    if pose.attrib:
        raise ValueError('Pose attributes / named reference frames are not supported.')
    values = tuple(float(v) for v in (pose.text or '').split())
    if len(values) != 6 or not all(math.isfinite(v) for v in values):
        raise ValueError('Expected six finite SDF pose values.')
    if abs(values[3]) > 1e-9 or abs(values[4]) > 1e-9:
        raise ValueError('Non-planar box projection requires a different converter.')
    return values


def compose(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, ...]:
    c, s = math.cos(a[5]), math.sin(a[5])
    return (a[0] + c*b[0] - s*b[1], a[1] + s*b[0] + c*b[1],
            a[2] + b[2], 0., 0., a[5] + b[5])


def load_walls(source: Path) -> list[dict]:
    root = ET.parse(source).getroot()
    if root.findall('.//include') or root.findall('.//model/model'):
        raise ValueError('Includes or nested models are not supported.')
    world = root.find('world')
    if world is None:
        raise ValueError('No SDF world found.')
    walls = []
    for model in world.findall('model'):
        if model.findtext('static', 'false').strip().lower() not in ('true', '1'):
            raise ValueError('Dynamic models require an explicit snapshot policy.')
        model_pose = pose_of(model)
        for link in model.findall('link'):
            link_pose = compose(model_pose, pose_of(link))
            for collision in link.findall('collision'):
                geometry = collision.find('geometry')
                if geometry is None:
                    raise ValueError('Missing collision geometry.')
                if geometry.find('plane') is not None:
                    continue
                size_text = geometry.findtext('box/size')
                if size_text is None:
                    raise ValueError('Only box collisions can be converted.')
                size = tuple(float(v) for v in size_text.split())
                if len(size) != 3 or not all(math.isfinite(v) for v in size) or min(size) <= 0:
                    raise ValueError('Invalid box dimensions.')
                local_pose = pose_of(collision)
                p = compose(link_pose, local_pose)
                if p[2] + size[2] / 2 <= 0:
                    continue
                x, y, z, _, _, yaw = p
                sx, sy, sz = size
                c, s = math.cos(yaw), math.sin(yaw)
                corners = [(x+c*u-s*v, y+s*u+c*v) for u,v in
                    [(-sx/2,-sy/2),(sx/2,-sy/2),(sx/2,sy/2),(-sx/2,sy/2)]]
                name = collision.get('name', '')
                visual = next((v for v in link.findall('visual')
                               if v.get('name') == name.removesuffix('_col') + '_vis'), None)
                matches = visual is not None and pose_of(visual) == local_pose and \
                    visual.findtext('geometry/box/size') == size_text
                walls.append(dict(name=name, model=model.get('name'), pose=list(p),
                                  size=list(size), corners=corners, polygon=Polygon(corners),
                                  visual_matches_collision=matches))
    if len(walls) != 16:
        raise ValueError(f'Expected 16 track boxes; found {len(walls)}.')
    return walls


def rasterize(walls: list[dict], resolution: float, interior) -> tuple[np.ndarray, dict]:
    geometry = unary_union([w['polygon'] for w in walls])
    xmin,ymin,xmax,ymax = geometry.bounds
    half_x = math.ceil((max(abs(xmin),abs(xmax)) + .1) / .05 - 1e-10) * .05
    half_y = math.ceil((max(abs(ymin),abs(ymax)) + .1) / .05 - 1e-10) * .05
    width = math.ceil(2*half_x/resolution - 1e-10)
    height = math.ceil(2*half_y/resolution - 1e-10)
    ox, oy = -width*resolution/2, -height*resolution/2
    # These arrays are bottom-up. Flip once when writing the image file.
    xs = ox + (np.arange(width)+.5)*resolution
    ys = oy + (np.arange(height)+.5)*resolution
    xx, yy = np.meshgrid(xs,ys)
    image = np.full((height,width),205,dtype=np.uint8)
    ix0,iy0,ix1,iy1 = interior.bounds
    image[(xx>ix0)&(xx<ix1)&(yy>iy0)&(yy<iy1)] = 254
    occupied = np.zeros(image.shape, dtype=bool)
    h = resolution/2
    # Exact separating-axis test for rectangle vs axis-aligned map cell.
    # A positive-area overlap marks a cell occupied. Boundary-only touch is not
    # enough. This preserves thin walls without introducing robot inflation.
    for w in walls:
        x,y,_,_,_,a = w['pose']; sx,sy,_ = w['size']
        c,s = math.cos(a),math.sin(a)
        dx,dy = xx-x,yy-y
        eps=1e-12
        hit = (np.abs(dx) < abs(c)*sx/2+abs(s)*sy/2+h-eps) & \
              (np.abs(dy) < abs(s)*sx/2+abs(c)*sy/2+h-eps) & \
              (np.abs(c*dx+s*dy) < sx/2+h*(abs(c)+abs(s))-eps) & \
              (np.abs(-s*dx+c*dy) < sy/2+h*(abs(c)+abs(s))-eps)
        occupied |= hit
    image[occupied] = 0
    metadata = dict(image='map_260905.pgm', mode='trinary', resolution=resolution,
                    origin=[round(ox,8),round(oy,8),0.0], negate=0,
                    occupied_thresh=0.65, free_thresh=0.196)
    return np.flipud(image), metadata


def create_plan(walls: list[dict], pocket, output: Path) -> None:
    width, height = 2000, 1340
    scale, cx, cy = 580., 980., 650.
    def pt(x: float, y: float): return (cx+scale*x, cy-scale*y)
    def poly_points(poly): return ' '.join(f'{u:.3f},{v:.3f}' for u,v in
                                          (pt(x,y) for x,y in poly.exterior.coords))
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#506779"/></marker>',
        '<pattern id="hatch" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="14" height="14" fill="#fff1d4"/><line x1="0" y1="0" x2="0" y2="14" stroke="#e3be79" stroke-width="2"/></pattern>',
        '</defs>', '<rect width="2000" height="1340" fill="#f4f6f8"/>']
    def text(x,y,value,size=24,fill='#263744',anchor='start',weight=400,extra=''):
        svg.append(f'<text x="{x:.2f}" y="{y:.2f}" font-family="DejaVu Sans, sans-serif" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" {extra}>{html.escape(value)}</text>')
    def line(x1,y1,x2,y2,stroke='#b8c5ce',sw=1.5,extra=''):
        svg.append(f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" stroke="{stroke}" stroke-width="{sw}" {extra}/>')
    def world_text(x,y,value,**kwargs):
        a,b=pt(x,y); text(a,b,value,**kwargs)
    def dim_x(x0,x1,y,label,offset=-14):
        a,b=pt(x0,y); c,d=pt(x1,y)
        line(a,b,c,d,stroke='#506779',sw=1.7,extra='marker-start="url(#arrow)" marker-end="url(#arrow)"')
        # Opaque small backing keeps dimensions readable over the reference grid.
        tw=len(label)*12.2+16
        svg.append(f'<rect x="{(a+c)/2-tw/2:.2f}" y="{b+offset-22:.2f}" width="{tw:.2f}" height="30" rx="5" fill="#ffffff" fill-opacity="0.94"/>')
        text((a+c)/2,b+offset,label,size=22,anchor='middle',fill='#405b6f',weight=600)
    text(80,82,'MAP 260905',size=46,weight=700)
    text(81,125,'TOP VIEW  /  SOURCE COLLISION GEOMETRY',size=21,fill='#657988')
    text(81,163,'map_260905.world  |  Exact XY scale  |  +X right, +Y up  |  Units: m',size=19,fill='#657988')
    cards=[(1080,'16','wall boxes'),(1360,'155 mm','wall height'),(1660,'10 mm','wall thickness')]
    for x,value,label in cards:
        svg.append(f'<rect x="{x}" y="45" width="245" height="115" rx="16" fill="#ffffff" stroke="#dde4e9"/>')
        text(x+22,96,value,size=32,weight=700)
        text(x+22,130,label,size=18,fill='#657988')
    bx0,bytop=pt(-1.3575,.6325); bx1,bybottom=pt(1.3575,-.6325)
    svg.append(f'<rect x="{bx0}" y="{bytop}" width="{bx1-bx0}" height="{bybottom-bytop}" fill="#ffffff"/>')
    # Reference grid is annotation only; it is absent from the occupancy map.
    for x in np.arange(-1.3,1.301,.1):
        u,v=pt(x,-.6225); u2,v2=pt(x,.6225)
        line(u,v,u2,v2,stroke='#e9eef1',sw=.8)
    for y in np.arange(-.6,.601,.1):
        u,v=pt(-1.3475,y); u2,v2=pt(1.3475,y)
        line(u,v,u2,v2,stroke='#e9eef1',sw=.8)
    for x in [-1.,-.5,0.,.5,1.]:
        u,v=pt(x,-.665); text(u,v,f'{x:g}',size=18,fill='#748897',anchor='middle')
    for y in [-.5,0.,.5]:
        u,v=pt(-1.39,y); text(u,v+6,f'{y:g}',size=18,fill='#748897',anchor='end')
    svg.append(f'<polygon points="{poly_points(pocket)}" fill="url(#hatch)"/>')
    for w in walls:
        svg.append(f'<polygon points="{poly_points(w["polygon"])}" fill="#243846"><title>{html.escape(w["name"])}</title></polygon>')
    # Main envelope dimensions are derived from the boxes, not the comment.
    top_y=.746
    for x in [-1.3575,1.3575]:
        u,v=pt(x,.6325); u2,v2=pt(x,top_y+.025); line(u,v-7,u2,v2)
    dim_x(-1.3575,1.3575,top_y,'2.715 m',offset=-15)
    dimx=1.47
    for y in [-.6325,.6325]:
        u,v=pt(1.3575,y); u2,v2=pt(dimx+.025,y); line(u+7,v,u2,v2)
    u,v=pt(dimx,-.6325); u2,v2=pt(dimx,.6325)
    line(u,v,u2,v2,stroke='#506779',sw=1.7,extra='marker-start="url(#arrow)" marker-end="url(#arrow)"')
    text(u+31,(v+v2)/2,'1.265 m',size=23,anchor='middle',fill='#405b6f',weight=600,
         extra=f'transform="rotate(-90 {u+31} {(v+v2)/2})"')
    # Labels do not name actual source zones; they describe the visible shapes.
    world_text(-1.065,.47,'LEFT BAY',size=24,anchor='middle',fill='#8394a1',weight=600)
    world_text(-.445,.43,'I-WALL',size=24,anchor='middle',fill='#8394a1',weight=600)
    world_text(.545,.48,'RECTILINEAR MAZE',size=22,anchor='middle',fill='#8394a1',weight=600)
    world_text(-.17,-.16,'CENTRAL LINK',size=20,anchor='middle',fill='#8394a1')
    world_text(-.7518,-.555,'ISOLATED POCKET',size=19,anchor='middle',fill='#8d641d',weight=700)
    # Gap at the exact leftmost corner of diag_0.
    diagonal=next(w for w in walls if w['name']=='diag_0_col')
    lx,ly=min(diagonal['corners'],key=lambda p:p[0])
    dim_x(-1.3475,lx,ly,'272 mm',offset=-15)
    dim_x(.76255,1.04755,.135,'285 mm',offset=-15)
    dim_x(1.05755,1.3475,.355,'290 mm',offset=-15)
    # World origin and axes are annotations, not obstacles.
    u,v=pt(0,0)
    svg.append(f'<circle cx="{u}" cy="{v}" r="5" fill="#507b95"/>')
    line(u-13,v,u+13,v,stroke='#507b95',sw=1.5)
    line(u,v-13,u,v+13,stroke='#507b95',sw=1.5)
    text(u-15,v-18,'(0, 0)',size=20,fill='#507b95',anchor='end')
    ax,ay=1830,1030
    line(ax,ay,ax+58,ay,stroke='#506779',sw=2,extra='marker-end="url(#arrow)"')
    line(ax,ay,ax,ay-58,stroke='#506779',sw=2,extra='marker-end="url(#arrow)"')
    text(ax+67,ay+6,'+X',size=19);text(ax,ay-70,'+Y',size=19,anchor='middle')
    # Summary band.
    line(80,1090,1920,1090,stroke='#d6e0e7',sw=2)
    svg.append('<rect x="82" y="1120" width="27" height="20" fill="#243846"/>')
    text(124,1137,'Collision wall',size=20)
    svg.append('<rect x="366" y="1120" width="27" height="20" fill="#ffffff" stroke="#cbd6df"/>')
    text(408,1137,'Empty geometry (not a clearance guarantee)',size=20)
    svg.append('<rect x="987" y="1120" width="27" height="20" fill="url(#hatch)"/>')
    text(1029,1137,'Disconnected empty region',size=20)
    # A scale bar with a true length of 0.5 m.
    sx,sy=1560,1131
    line(sx,sy,sx+scale*.5,sy,stroke='#243846',sw=4)
    line(sx,sy-7,sx,sy+7,stroke='#243846',sw=2)
    line(sx+scale*.5,sy-7,sx+scale*.5,sy+7,stroke='#243846',sw=2)
    text(sx+scale*.25,sy-14,'0.5 m',size=19,anchor='middle')
    text(82,1193,'GEOMETRY CHECK',size=18,fill='#5a7080',weight=700)
    text(82,1226,'v2 review: source geometry retained. Box envelope: 2.715 x 1.265 m / 10 mm walls.',size=22)
    text(82,1265,'The lower X pocket is closed by the bottom wall. Gap labels are rounded to the nearest millimetre.',size=21,fill='#657988')
    text(82,1302,'No source geometry altered. No robot footprint, obstacle inflation, sensor visibility or live simulation validation applied.',size=19,fill='#657988')
    svg.append('</svg>')
    path=output/'map_260905_plan.svg'
    path.write_text('\n'.join(svg),encoding='utf-8')
    cairosvg.svg2png(url=str(path),write_to=str(output/'map_260905_plan.png'))


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('world',type=Path)
    parser.add_argument('--out',type=Path,default=Path('map_260905_package'))
    parser.add_argument('--resolution',type=float,default=.005)
    args=parser.parse_args()
    if not 0 < args.resolution <= .01:
        parser.error('Use a resolution in (0, 0.01] m/pixel for the 10 mm walls.')
    args.out.mkdir(parents=True,exist_ok=True)
    walls=load_walls(args.world)
    by_name={w['name']:w for w in walls}
    geometry=unary_union([w['polygon'] for w in walls])
    interior=box(by_name['wall_00_col']['polygon'].bounds[2],
                 by_name['wall_02_col']['polygon'].bounds[3],
                 by_name['wall_01_col']['polygon'].bounds[0],
                 by_name['wall_03_col']['polygon'].bounds[1])
    empty=interior.difference(geometry)
    regions=sorted(list(empty.geoms) if hasattr(empty,'geoms') else [empty],key=lambda p:-p.area)
    if len(regions) != 2:
        raise ValueError('Source topology differs from expected main region plus X pocket.')
    raster,metadata=rasterize(walls,args.resolution,interior)
    Image.fromarray(raster).save(args.out/'map_260905.pgm')
    Image.fromarray(raster).save(args.out/'map_260905_occupancy.png')
    (args.out/'map_260905.yaml').write_text(yaml.safe_dump(metadata,sort_keys=False),encoding='utf-8')
    # A PNG alternative metadata file is included for viewers lacking PGM support.
    png_metadata={**metadata,'image':'map_260905_occupancy.png'}
    (args.out/'map_260905_png.yaml').write_text(yaml.safe_dump(png_metadata,sort_keys=False),encoding='utf-8')
    create_plan(walls,regions[1],args.out)
    gaps={
        'right_outer_aisle':('wall_01_col','wall_13_col'),
        'right_inner_parallel_aisle':('wall_12_col','wall_13_col'),
        'left_wall_to_nearest_X_tip':('wall_00_col','diag_0_col')}
    raw_walls=[{k:v for k,v in w.items() if k!='polygon'} for w in walls]
    (args.out/'wall_geometry.json').write_text(json.dumps(raw_walls,indent=2),encoding='utf-8')
    components4,n4=ndimage.label(raster==254)
    components8,n8=ndimage.label(raster==254,structure=np.ones((3,3),dtype=int))
    ox,oy,_=metadata['origin']; h,w=raster.shape
    def cell_at(x,y):
        col=int(math.floor((x-ox)/args.resolution))
        row=h-1-int(math.floor((y-oy)/args.resolution))
        if not (0<=row<h and 0<=col<w): raise ValueError('Probe outside map bounds.')
        return row,col
    probes={'world_origin':(0.,0.,254),'left_wall':(-1.3525,0.,0),
            'right_aisle':(1.2,0.,254),'inner_aisle':(.9,.14,254),
            'X_center':(-.7518,-.30857,0), 'X_pocket':(-.7518,-.54,254),
            'outside_track':(1.45,.7,205)}
    results={}
    for name,(x,y,value) in probes.items():
        row,col=cell_at(x,y)
        actual=int(raster[row,col]); assert actual==value,(name,actual,value)
        results[name]=dict(world=[x,y],row=row,column=col,pixel=actual,expected=value,passed=True)
    assert n4==2 and n8==2,(n4,n8)
    assert components8[cell_at(0,0)]!=components8[cell_at(-.7518,-.54)]
    assert np.array_equal(np.asarray(Image.open(args.out/'map_260905.pgm')),raster)
    assert np.array_equal(np.asarray(Image.open(args.out/'map_260905_occupancy.png')),raster)
    assert all(v['visual_matches_collision'] for v in walls)
    report=dict(source_file=args.world.name,source_sha256=hashlib.sha256(args.world.read_bytes()).hexdigest(),
        interpretation='Exact XY projection of source static collision boxes; no collision geometry edits.',
        wall_count=len(walls),all_visual_boxes_match_collisions=True,
        original_upload_comment=dict(nominal_size_m=[2.710,1.260],wall_thickness_m=.005),
        collision_geometry=dict(bounds_m=list(geometry.bounds),outer_size_m=[geometry.bounds[2]-geometry.bounds[0],geometry.bounds[3]-geometry.bounds[1]],
                                wall_thickness_m=.01,wall_height_m=.155,z_range_m=[0,.155]),
        interior_rectangle_m=list(interior.bounds),
        empty_regions=[dict(area_m2=r.area,centroid_m=list(r.centroid.coords)[0],bounds_m=list(r.bounds),
                            description='main connected empty region' if i==0 else 'isolated lower X pocket') for i,r in enumerate(regions)],
        measured_gaps={k:dict(walls=list(pair),distance_m=by_name[pair[0]]['polygon'].distance(by_name[pair[1]]['polygon'])) for k,pair in gaps.items()},
        raster=dict(**metadata,width_px=w,height_px=h,pixel_counts={str(int(k)):int(v) for k,v in zip(*np.unique(raster,return_counts=True))},
                    method='Positive-area cell/box intersection (SAT); conservative boundary extension is bounded by one cell diagonal.',
                    outside_policy='Unknown outside the rectangular track; this is an export policy, not a source obstacle.',
                    robot_inflation_applied=False,free_components_4_neighbour=n4,free_components_8_neighbour=n8),
        checks=dict(pixel_probes=results,image_roundtrip_passed=True,world_orientation_preserved=True,
                    disconnected_pocket_preserved=True,simulation_executed=False,nav2_runtime_executed=False),
        limitations=['No robot, footprint, spawn pose, LiDAR mount or scan plane is defined in this source.',
                     'Empty cells are geometric free space, not proof of navigability for a finite robot.',
                     'The closed X pocket is retained as empty space; no doorway has been invented.',
                     'Original upload comments differed from geometry; v2 documents model dimensions without claiming physical CAD verification.',
                     'PNG/SVG preview annotations are not present in the occupancy map.'],
        format_references=['https://raw.githubusercontent.com/ros-navigation/navigation2/jazzy/nav2_map_server/src/map_io.cpp',
                           'https://index.ros.org/p/nav2_map_server/'])
    (args.out/'validation_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    source_target=args.out/args.world.name
    if args.world.resolve()!=source_target.resolve(): shutil.copy2(args.world,source_target)
    (args.out/'requirements.txt').write_text('numpy\nPillow\nshapely>=2\nscipy\nPyYAML\ncairosvg\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['wall_count','collision_geometry','empty_regions','measured_gaps','raster']},indent=2))

if __name__=='__main__':
    try:
        main()
    except (OSError,ValueError,ET.ParseError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        raise SystemExit(1)
