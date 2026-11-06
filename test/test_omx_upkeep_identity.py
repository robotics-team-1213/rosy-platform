"""Pure filesystem/trace fixtures: diagnostic recovery never guesses a device owner."""
import glob
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'deploy/robot/omx'))
import cell_upkeep as cu
import jitter_replay as jr
from test_omx_cell_upkeep import CAMS, DEV, Usb, health_log, make_io
from test_omx_joint_jitter import trace


def sysfs(tmp_path, monkeypatch, board_root='3-2'):
    """USB3 camera on4-port2, USB2 companion3-port2; no real /dev or /sys access."""
    def touch(path, text=''):
        path.parent.mkdir(parents=True, exist_ok=True);path.write_text(text)
    def link(path, target):
        path.parent.mkdir(parents=True, exist_ok=True);path.symlink_to(target)
    camera=tmp_path/'dev/video0';touch(camera)
    byid=tmp_path/'dev/v4l/by-id/camera';link(byid,camera)
    usb=tmp_path/'sys/devices/pci/usb4/4-2/4-2.1'
    touch(usb/'idVendor','8086');touch(usb/'speed','5000')
    link(tmp_path/'sys/class/video4linux/video0/device',usb)
    root=tmp_path/'sys/devices/pci/usb4/4-0:1.0/usb4-port2';root.mkdir(parents=True)
    peer=tmp_path/'sys/devices/pci/usb3/3-0:1.0/usb3-port2';peer.mkdir(parents=True)
    touch(root/'disable','0');touch(peer/'disable','0')
    link(root/'peer',peer)
    link(tmp_path/'sys/bus/usb/devices/4-0:1.0',root.parent)
    tty=tmp_path/'dev/ttyACM0';touch(tty)
    board=tmp_path/f'sys/devices/pci/usb{board_root.split("-")[0]}/{board_root}/{board_root}.7:1.0/tty/ttyACM0'
    board.mkdir(parents=True)
    link(tmp_path/'sys/class/tty/ttyACM0/device',board)
    board_id=tmp_path/'dev/serial/by-id/usb-ROBOTIS_OpenRB-150_TEST-if00'
    link(board_id,tty)
    original_realpath, original_glob = os.path.realpath, glob.glob
    def mapped(path):
        value=str(path)
        return tmp_path/value.lstrip('/') if value=='/sys' or value.startswith(('/sys/','/dev/')) else Path(value)
    roots=[]
    class FixturePath(type(Path())):
        def __new__(cls,*args):
            return super().__new__(cls,mapped(Path(*args)))
        @property
        def parent(self):
            parent=super().parent
            if parent==self:
                roots.append(str(self))
                if len(roots)>4:
                    raise AssertionError('unbounded USB ancestor walk')
            return parent
    monkeypatch.setattr(cu,'Path',FixturePath)
    monkeypatch.setattr(cu.os.path,'realpath',lambda p,*a,**kw: original_realpath(mapped(p),*a,**kw))
    monkeypatch.setattr(cu.glob,'glob',lambda pattern: original_glob(str(mapped(pattern))))
    return byid,usb,root,peer,board_id


@pytest.mark.parametrize('board_root',['4-2','3-2'])
def test_every_cycled_port_including_usb2_peer_is_checked_before_recovery(tmp_path,monkeypatch,board_root):
    camera,_usb,_root,_peer,board=sysfs(tmp_path,monkeypatch,board_root)
    usb=Usb();io=usb.io();io.device=lambda role:str(camera);io.usb_port=cu.usb_port
    note=cu.usb_recover('arm_a_wrist',io)
    assert 'refused' in note and board.name in note
    assert usb.log==[]  # no unit change, direct read or port write on shared hardware


def test_adjacent_port_name_is_not_a_descendant_of_the_powered_port(tmp_path,monkeypatch):
    camera,*_=sysfs(tmp_path,monkeypatch,'3-20')
    assert cu.usb_port(camera)['boards']==[]


@pytest.mark.parametrize('missing',['device','video_sysfs','usb_ancestor','root_ancestor','peer'])
def test_missing_usb_chain_is_bounded_and_explicit_oserror(tmp_path,monkeypatch,missing):
    camera,usb,root,peer,_=sysfs(tmp_path,monkeypatch)
    if missing=='device':camera.unlink()
    elif missing=='video_sysfs':(tmp_path/'sys/class/video4linux/video0/device').unlink()
    elif missing=='usb_ancestor':(usb/'idVendor').unlink()
    elif missing=='root_ancestor':
        (tmp_path/'sys/class/video4linux/video0/device').unlink()
        wrong=tmp_path/'sys/not-a-usb-root/4-2.1';wrong.mkdir(parents=True)
        (wrong/'idVendor').write_text('8086');(wrong/'speed').write_text('5000')
        (tmp_path/'sys/class/video4linux/video0/device').symlink_to(wrong)
    else:
        (root/'peer').unlink();(root/'peer').symlink_to(tmp_path/'missing-peer')
    with pytest.raises(OSError):cu.usb_port(camera)


def write_trace(path,shaky=True):
    path.write_text('\n'.join(json.dumps(row) for row in (trace(4,4.0,0.6) if shaky else trace(4))))


def test_simultaneous_arms_use_explicit_trace_name_not_first_health_mtime(tmp_path):
    a,b=tmp_path/'motor-health-a.jsonl',tmp_path/'motor-health-b.jsonl'
    health_log(a,pwm=0);health_log(b,pwm=0)
    b.write_text(b.read_text().replace('FF06202D','FF061D2D'))
    trace_b=tmp_path/'trace-arm_b-shaky.jsonl';write_trace(trace_b)
    for path,stamp in ((a,1000),(b,1001),(trace_b,1002)):os.utime(path,(stamp,stamp))
    result=jr.replay([trace_b],[a,b])
    assert not result['arm_a']['flagged']
    assert result['arm_b']['flagged']
    io,_=make_io();io.replays=lambda h,t,p:({},jr.replay(t,h,p))
    assert cu.check_monitors('arm_b',DEV.replace('FF06202D','FF061D2D'),tmp_path,0,None,io)['status']=='warn'


def test_anonymous_trace_is_never_assigned_by_mtime_or_used_to_clear_an_arm(tmp_path):
    health=tmp_path/'motor-health-a.jsonl';health_log(health,pwm=0)
    anonymous=tmp_path/'trace-unknown-session.jsonl';write_trace(anonymous,shaky=False)
    result=jr.replay([anonymous],[health])
    assert 'trace' in result and result['arm_a']['trace_h']==0
    io,_=make_io();io.replays=lambda h,t,p:({},jr.replay(t,h,p))
    checked=cu.check_monitors('arm_a',DEV,tmp_path,0,None,io)
    assert checked['status']=='warn' and 'identity' in checked['detail']
