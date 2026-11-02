"""Finger collision for the mapped OMX stacking scene (split from stacking_task, D-766).

The imported finger hulls are switched off and each finger collides through exactly one primitive: the Gazebo-calibrated
capsule for the stock jaw, or the box on the mesh pad face for the opt-in palletizing jaw v2.1.
"""
import math

import palletizing_gripper as palletizing
from run_omx_backend import PAD_CONTACT_OFFSET_M, PAD_HALF_LENGTH, PAD_RADIUS, PAD_REST_OFFSET_M, jaw_contact_point


def add_finger_pads(stage, tool, gripper=None):
    from pxr import Gf, PhysxSchema, Usd, UsdGeom, UsdPhysics, UsdShade
    contact, rest = (PAD_CONTACT_OFFSET_M, PAD_REST_OFFSET_M) if gripper is None else (
        palletizing.PAD_CONTACT_OFFSET_M, palletizing.PAD_REST_OFFSET_M)
    x, y = jaw_contact_point()
    for finger, side in (('link6', 1), ('link7', -1)):
        body = stage.GetPrimAtPath(tool[finger])
        disabled = 0
        for prim in Usd.PrimRange(body):
            if prim.HasAPI(UsdPhysics.CollisionAPI):
                UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Set(False)
                disabled += 1
        if disabled == 0:
            raise RuntimeError('Imported finger collision hull was not found')
        if gripper is None:
            pad = UsdGeom.Capsule.Define(stage, body.GetPath().AppendChild('grip_pad'))
            pad.CreateAxisAttr('Z'); pad.CreateRadiusAttr(PAD_RADIUS); pad.CreateHeightAttr(2*PAD_HALF_LENGTH)
            UsdGeom.Xformable(pad).AddTranslateOp().Set(Gf.Vec3d(x, side*(y+PAD_RADIUS), 0.))
        else:
            centre, size, angle = palletizing.pad_box(side)  # metres and radians, in the finger link frame
            pad = UsdGeom.Cube.Define(stage, body.GetPath().AppendChild('grip_pad'))
            pad.CreateSizeAttr(1.)
            pose = UsdGeom.Xformable(pad)
            pose.AddTranslateOp().Set(Gf.Vec3d(*centre))
            pose.AddRotateZOp().Set(math.degrees(angle))
            pose.AddScaleOp().Set(Gf.Vec3f(*size))
        pad.CreatePurposeAttr('guide')
        UsdPhysics.CollisionAPI.Apply(pad.GetPrim())
        offsets = PhysxSchema.PhysxCollisionAPI.Apply(pad.GetPrim())
        offsets.CreateContactOffsetAttr(contact)
        offsets.CreateRestOffsetAttr(rest)
        UsdShade.MaterialBindingAPI.Apply(pad.GetPrim()).Bind(UsdShade.Material.Get(stage, '/World/GripMaterial'),
            UsdShade.Tokens.weakerThanDescendants, 'physics')
        enabled = [p for p in Usd.PrimRange(body) if p.HasAPI(UsdPhysics.CollisionAPI)
                   and UsdPhysics.CollisionAPI(p).GetCollisionEnabledAttr().Get()]
        if len(enabled) != 1 or enabled[0].GetPath() != pad.GetPath():
            raise RuntimeError('Each finger requires exactly its calibrated pad collider')
