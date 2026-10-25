"""Birds-eye cache shared by the lane follower and paint localizer."""

def cached_birds_eye(owner, ground, shape):
    key = (ground.height_m, ground.pitch_rad, ground.focal_px, ground.principal_x,
           ground.principal_y, ground.max_range_m, shape[0], shape[1], owner._camera_x)
    if key != owner._view_key:
        from .lane_bev import BirdsEye
        owner._view = BirdsEye(ground, shape[1], shape[0], owner._camera_x)
        owner._view_key = key
    return owner._view
