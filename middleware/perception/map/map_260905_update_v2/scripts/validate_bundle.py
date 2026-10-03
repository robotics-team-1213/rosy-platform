#!/usr/bin/env python3
"""Static checks only. Does not run Gazebo, ROS, Nav2 or hardware."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image
from scipy import ndimage
import shapely
from shapely.geometry import box
from shapely.ops import unary_union
import yaml
from generate_map import load_walls, rasterize

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL_SHA='8475464857322d71f6e492171419bf285e7bd034089b90ad59d6f106b0941072'  # checksum of the uploaded source world
PREVIOUS_PGM_SHA='d23141945700bf9725bc0c2407425abffe4fa93b1167146bf8f259a35a4cd21c'  # checksum of the previously delivered PGM

def require(condition: bool, text: str) -> None:
    if not condition:
        raise ValueError(text)

def semantic(element: ET.Element) -> tuple:
    return (element.tag,tuple(sorted(element.attrib.items())),(element.text or '').strip(),
            tuple(semantic(child) for child in element))

def validate() -> dict:
    orig=ROOT/'original/map_260905.world'
    updated=ROOT/'worlds/map_260905.world'
    require(hashlib.sha256(orig.read_bytes()).hexdigest()==ORIGINAL_SHA,'Original upload bytes changed.')
    r0=ET.parse(orig).getroot(); r1=ET.parse(updated).getroot()
    m0=r0.findall('./world/model'); m1=r1.findall('./world/model')
    require([semantic(x) for x in m0]==[semantic(x) for x in m1],
            'Model pose/geometry/material/surface or another model property changed.')
    require(r0.find('world').get('name')==r1.find('world').get('name'),'World name changed.')
    engine=r1.findtext('./world/plugin[@name="gz::sim::systems::Physics"]/engine/filename')
    require(engine=='gz-physics-dartsim-plugin','Unexpected requested engine.')
    p0=r0.find('./world/physics');p1=r1.find('./world/physics')
    require(p1.get('name')=='track_1ms' and p1.get('type')=='dart','Physics profile metadata mismatch.')
    require([semantic(c) for c in p0]==[semantic(c) for c in p1],'Physics numerical settings changed.')
    walls=load_walls(updated)
    require(all(w['visual_matches_collision'] for w in walls),'Visual/collision mismatch.')
    by={w['name']:w for w in walls}
    union=unary_union([w['polygon'] for w in walls])
    require(np.allclose(union.bounds,[-1.3575,-0.6325,1.3575,0.6325],rtol=0,atol=1e-10),'Bounds differ.')
    interior=box(by['wall_00_col']['polygon'].bounds[2],by['wall_02_col']['polygon'].bounds[3],
                 by['wall_01_col']['polygon'].bounds[0],by['wall_03_col']['polygon'].bounds[1])
    meta=yaml.safe_load((ROOT/'maps/map_260905.yaml').read_text())
    expected,derived=rasterize(walls,0.005,interior)
    require(meta==derived,'Map metadata differs from regeneration.')
    pgm_sha=hashlib.sha256((ROOT/'maps'/meta['image']).read_bytes()).hexdigest()
    require(pgm_sha==PREVIOUS_PGM_SHA,'PGM differs from previous delivered map bytes.')
    image=np.asarray(Image.open(ROOT/'maps'/meta['image']))
    png=np.asarray(Image.open(ROOT/'maps/map_260905_occupancy.png'))
    require(image.shape==(300,600),'Wrong map dimensions.')
    require(np.array_equal(image,expected) and np.array_equal(image,png),'Raster roundtrip mismatch.')
    require(set(np.unique(image).tolist())=={0,205,254},'Unexpected pixel classes.')
    for connectivity in [1,2]:
        labels,n=ndimage.label(image==254,ndimage.generate_binary_structure(2,connectivity))
        require(n==2,'Free-space connected components differ.')
    ox,oy,_=meta['origin'];res=meta['resolution'];height,width=image.shape
    def sample(x: float,y: float) -> tuple[int,int]:
        return height-1-math.floor((y-oy)/res),math.floor((x-ox)/res)
    a=sample(0,0);b=sample(-0.7518,-0.54)
    require(image[a]==254 and image[b]==254 and labels[a]!=labels[b],'X pocket separation failed.')
    # Independent area intersection uses GEOS, not the SAT rasterization routine.
    xs=ox+np.arange(width)*res;ys=oy+np.arange(height)*res
    xx,yy=np.meshgrid(xs,ys)
    cells=shapely.box(xx.ravel(),yy.ravel(),xx.ravel()+res,yy.ravel()+res)
    overlaps=shapely.area(shapely.intersection(cells,union))>1e-15
    observed=np.flipud(image==0).ravel()
    mismatches=int(np.count_nonzero(overlaps!=observed))
    require(mismatches==0,'Independent cell intersection mismatch.')
    # Unknown 205 must remain between the map's free and occupied thresholds.
    occ=(255-image.astype(float))/255
    require(np.all(occ[image==205]>meta['free_thresh']) and
            np.all(occ[image==205]<meta['occupied_thresh']),'Unknown pixel interpreted as free/occupied.')
    report={
      'status':'PASS_STATIC_CHECKS_ONLY',
      'source_sha256':hashlib.sha256(orig.read_bytes()).hexdigest(),
      'updated_world_sha256':hashlib.sha256(updated.read_bytes()).hexdigest(),
      'all_model_semantics_unchanged':True,'wall_count':len(walls),
      'visual_collision_pairs_match':True,'physics_numerical_values_unchanged':True,
      'requested_engine':engine,'world_bounds_m':list(union.bounds),
      'map_width_px':width,'map_height_px':height,'resolution_m':res,'origin':meta['origin'],
      'pgm_sha256':hashlib.sha256((ROOT/'maps/map_260905.pgm').read_bytes()).hexdigest(),
      'matches_previous_occupancy_bytes':True,
      'regeneration_pixel_mismatches':int(np.count_nonzero(image!=expected)),
      'independent_GEOS_cell_intersections':int(image.size),
      'independent_cell_mismatches':mismatches,'free_components_4_and_8_neighbour':[2,2],
      'closed_X_pocket_preserved':True,'raster_boundary_upper_bound_m':math.sqrt(2)*res,
      'tests_not_run':['Gazebo SDFormat parser','Gazebo plugin loading','Gazebo collision dynamics',
                       'ROS/Nav2 runtime','robot footprint clearance','physical hardware safety'],
      'runtime_execution_performed':False,
    }
    (ROOT/'reports/package_validation.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    try:
        print(json.dumps(validate(),indent=2))
    except (OSError,ValueError,ET.ParseError,yaml.YAMLError) as exc:
        print(f'FAIL: {exc}',file=sys.stderr)
        raise SystemExit(1)
