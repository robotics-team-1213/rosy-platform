"""Pure-Python lens distortion, Hartley-normalized DLT, SE(3) planar pose, and parallax math."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

Point = tuple[float, float]
MIN_CAMERA_HEIGHT_M = 0.3
MAX_CAMERA_HEIGHT_M = 10.0


def _finite(v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        raise ValueError("expected finite number")
    return float(v)


def validate_lens_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a pinhole/fisheye lens intrinsics profile."""
    if not isinstance(profile, Mapping):
        raise ValueError("lens_profile must be a mapping")
    model = profile.get("model")
    if model not in ("pinhole", "fisheye"):
        raise ValueError("lens_profile.model must be 'pinhole' or 'fisheye'")
    raw_k = profile.get("K")
    if not isinstance(raw_k, (list, tuple)) or len(raw_k) != 3:
        raise ValueError("lens_profile.K must be a 3x3 matrix")
    k = [[_finite(v) for v in row] if isinstance(row, (list, tuple)) and len(row) == 3 else None for row in raw_k]
    if any(r is None for r in k):
        raise ValueError("lens_profile.K must be a 3x3 matrix")
    if k[0][0] <= 0.0 or k[1][1] <= 0.0 or k[0][1] != 0.0 or k[1][0] != 0.0 or k[2] != [0.0, 0.0, 1.0]:
        raise ValueError("lens_profile.K is invalid")
    expected_d = 5 if model == "pinhole" else 4
    raw_d = profile.get("D")
    if not isinstance(raw_d, (list, tuple)) or len(raw_d) != expected_d:
        raise ValueError(f"lens_profile.D must have {expected_d} coefficients for {model}")
    d = [_finite(v) for v in raw_d]
    raw_size = profile.get("image_size")
    if (not isinstance(raw_size, (list, tuple)) or len(raw_size) != 2
            or any(type(v) is not int or not 32 <= v <= 8192 for v in raw_size)):
        raise ValueError("lens_profile.image_size must be two integers in 32..8192")
    out: dict[str, Any] = {"model": model, "K": k, "D": d, "image_size": [int(raw_size[0]), int(raw_size[1])]}
    source = profile.get("source")
    if source is not None:
        if source not in ("measured", "nominal", "auto"):
            raise ValueError("lens_profile.source is invalid")
        out["source"] = source
    revision = profile.get("revision")
    if revision is not None:
        if not isinstance(revision, str) or not revision.strip() or len(revision) > 160:
            raise ValueError("lens_profile.revision is invalid")
        out["revision"] = revision
    reproj = profile.get("reproj_p95_px")
    if reproj is not None:
        val = _finite(reproj)
        if val < 0.0:
            raise ValueError("lens_profile.reproj_p95_px must be non-negative")
        out["reproj_p95_px"] = val
    return out


def scale_lens_profile(profile: Mapping[str, Any], target_size: Sequence[int], *, aspect_tol: float = 0.01) -> dict[str, Any]:
    """Rescale validated lens intrinsics to ``target_size`` by pixel centres."""
    clean = validate_lens_profile(profile)
    tw, th = int(target_size[0]), int(target_size[1])
    if tw < 32 or th < 32 or tw > 8192 or th > 8192:
        raise ValueError("target_size out of range")
    sw, sh = clean["image_size"]
    if (tw, th) == (sw, sh):
        return clean
    sx, sy = tw / sw, th / sh
    if abs(sx / sy - 1.0) > aspect_tol:
        raise ValueError("target_size aspect differs from lens_profile")
    k = [row[:] for row in clean["K"]]
    k[0][0] *= sx
    k[1][1] *= sy
    k[0][2] = sx * (k[0][2] + 0.5) - 0.5
    k[1][2] = sy * (k[1][2] + 0.5) - 0.5
    return {**clean, "K": k, "image_size": [tw, th]}


def default_lens_profile(width: int, height: int, hfov_deg: float = 67.8) -> dict[str, Any]:
    """Nominal pinhole profile from image size and horizontal/long-side FOV."""
    if not 0.0 < hfov_deg < 180.0:
        raise ValueError("hfov_deg out of range")
    f = (max(float(width), float(height)) / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    return {
        "model": "pinhole",
        "K": [[f, 0.0, float(width) / 2.0], [0.0, f, float(height) / 2.0], [0.0, 0.0, 1.0]],
        "D": [0.0, 0.0, 0.0, 0.0, 0.0],
        "image_size": [int(width), int(height)],
        "source": "nominal",
    }


def distort_normalized(xn: float, yn: float, model: str, d: Sequence[float]) -> Point:
    """Apply pinhole Brown-Conrady or fisheye Kannala-Brandt distortion to normalized rays."""
    if model == "fisheye":
        r = math.hypot(xn, yn)
        if r < 1e-12:
            return xn, yn
        th = math.atan(r)
        t2 = th * th
        thd = th * (1.0 + d[0] * t2 + d[1] * t2 * t2 + d[2] * (t2 ** 3) + d[3] * (t2 ** 4))
        scale = thd / r
        return xn * scale, yn * scale
    r2 = xn * xn + yn * yn
    k1, k2, p1, p2 = d[0], d[1], d[2], d[3]
    k3 = d[4] if len(d) > 4 else 0.0
    rad = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
    xd = xn * rad + 2.0 * p1 * xn * yn + p2 * (r2 + 2.0 * xn * xn)
    yd = yn * rad + p1 * (r2 + 2.0 * yn * yn) + 2.0 * p2 * xn * yn
    return xd, yd


def distort_point(xu: float, yu: float, profile: Mapping[str, Any]) -> Point:
    """Map an undistorted pixel ``(xu, yu)`` in ``K`` space to raw distorted pixel."""
    k, d, model = profile["K"], profile["D"], profile["model"]
    xn = (xu - k[0][2]) / k[0][0]
    yn = (yu - k[1][2]) / k[1][1]
    xd, yd = distort_normalized(xn, yn, model, d)
    return xd * k[0][0] + k[0][2], yd * k[1][1] + k[1][2]


def undistort_point(u: float, v: float, profile: Mapping[str, Any]) -> Point:
    """Invert ``distort_point`` via damped 2x2 Newton iteration."""
    k, d, model = profile["K"], profile["D"], profile["model"]
    if not any(abs(c) > 1e-12 for c in d):
        return float(u), float(v)
    fx, fy, cx, cy = k[0][0], k[1][1], k[0][2], k[1][2]
    xd_t, yd_t = (float(u) - cx) / fx, (float(v) - cy) / fy
    xn, yn = xd_t, yd_t
    eps = 1e-6
    for _ in range(16):
        fx0, fy0 = distort_normalized(xn, yn, model, d)
        rx, ry = fx0 - xd_t, fy0 - yd_t
        err = rx * rx + ry * ry
        if err < 1e-20:
            break
        fxx, fyx = distort_normalized(xn + eps, yn, model, d)
        fxy, fyy = distort_normalized(xn, yn + eps, model, d)
        j00, j10 = (fxx - fx0) / eps, (fyx - fy0) / eps
        j01, j11 = (fxy - fx0) / eps, (fyy - fy0) / eps
        det = j00 * j11 - j01 * j10
        if abs(det) < 1e-12:
            break
        dx = -(j11 * rx - j01 * ry) / det
        dy = -(-j10 * rx + j00 * ry) / det
        step = 1.0
        while step >= 0.0625:
            nx, ny = xn + step * dx, yn + step * dy
            tx, ty = distort_normalized(nx, ny, model, d)
            if (tx - xd_t) ** 2 + (ty - yd_t) ** 2 <= err + 1e-22:
                xn, yn = nx, ny
                break
            step *= 0.5
        if math.hypot(step * dx, step * dy) < 1e-11:
            break
    return xn * fx + cx, yn * fy + cy


def _det3(h: Sequence[float]) -> float:
    a, b, c, d, e, f, g, i, j = h
    return a * (e * j - f * i) - b * (d * j - f * g) + c * (d * i - e * g)


def _invert3(h: Sequence[float]) -> list[float]:
    a, b, c, d, e, f, g, i, j = h
    c00, c01, c02 = e * j - f * i, -(d * j - f * g), d * i - e * g
    det = a * c00 + b * c01 + c * c02
    if not math.isfinite(det) or abs(det) < 1e-18:
        raise ValueError("singular 3x3 matrix")
    inv_d = 1.0 / det
    return [
        c00 * inv_d, -(b * j - c * i) * inv_d, (b * f - c * e) * inv_d,
        c01 * inv_d, (a * j - c * g) * inv_d, -(a * f - c * d) * inv_d,
        c02 * inv_d, -(a * i - b * g) * inv_d, (a * e - b * d) * inv_d,
    ]


def _matmul3(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [
        sum(a[r * 3 + k] * b[k * 3 + c] for k in range(3))
        for r in range(3) for c in range(3)
    ]


def _hartley(pts: Sequence[Point]) -> tuple[list[Point], list[float]]:
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    dists = [math.hypot(p[0] - mx, p[1] - my) for p in pts]
    mean_d = sum(dists) / n
    if not math.isfinite(mean_d) or mean_d < 1e-12:
        raise ValueError("degenerate point spread")
    s = math.sqrt(2.0) / mean_d
    normed = [((p[0] - mx) * s, (p[1] - my) * s) for p in pts]
    t = [s, 0.0, -s * mx, 0.0, s, -s * my, 0.0, 0.0, 1.0]
    return normed, t


def _smallest_eigvec_sym(mat: list[list[float]]) -> list[float]:
    """Jacobi symmetric eigensolver returning the eigenvector for the smallest eigenvalue."""
    n = len(mat)
    a = [row[:] for row in mat]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(32):
        max_val, p, q = 0.0, 0, 1
        for i in range(n):
            for j in range(i + 1, n):
                val = abs(a[i][j])
                if val > max_val:
                    max_val, p, q = val, i, j
        if max_val < 1e-15:
            break
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        tau = (aqq - app) / (2.0 * apq)
        t = (1.0 / (abs(tau) + math.hypot(1.0, tau))) * (1.0 if tau >= 0.0 else -1.0)
        c = 1.0 / math.hypot(1.0, t)
        s = t * c
        a[p][p] = app - t * apq
        a[q][q] = aqq + t * apq
        a[p][q] = a[q][p] = 0.0
        for r in range(n):
            if r != p and r != q:
                arp, arq = a[r][p], a[r][q]
                a[r][p] = a[p][r] = c * arp - s * arq
                a[r][q] = a[q][r] = s * arp + c * arq
            vrp, vrq = v[r][p], v[r][q]
            v[r][p] = c * vrp - s * vrq
            v[r][q] = s * vrp + c * vrq
    idx = min(range(n), key=lambda i: a[i][i])
    return [v[r][idx] for r in range(n)]


def fit_homography_dlt(src_pts: Sequence[Point], dst_pts: Sequence[Point]) -> list[float]:
    """Hartley-normalized DLT homography for ``N >= 4`` point pairs."""
    if len(src_pts) != len(dst_pts) or len(src_pts) < 4:
        raise ValueError("homography needs at least four point pairs")
    src_n, t_src = _hartley(src_pts)
    dst_n, t_dst = _hartley(dst_pts)
    ata = [[0.0] * 9 for _ in range(9)]
    for (u, v), (x, y) in zip(src_n, dst_n):
        for row in (
            [u, v, 1.0, 0.0, 0.0, 0.0, -x * u, -x * v, -x],
            [0.0, 0.0, 0.0, u, v, 1.0, -y * u, -y * v, -y],
        ):
            for i in range(9):
                ri = row[i]
                if ri:
                    for j in range(i, 9):
                        ata[i][j] += ri * row[j]
    for i in range(9):
        for j in range(i):
            ata[i][j] = ata[j][i]
    h_norm = _smallest_eigvec_sym(ata)
    h = _matmul3(_invert3(t_dst), _matmul3(h_norm, t_src))
    scale = max(abs(val) for val in h)
    if scale < 1e-12 or abs(_det3(h)) / (scale ** 3) < 1e-11:
        raise ValueError("degenerate homography")
    if abs(h[8]) > 1e-12:
        h = [val / h[8] for val in h]
    return h


def _solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    aug = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[piv][col]) < 1e-14:
            raise ValueError("singular linear system")
        aug[col], aug[piv] = aug[piv], aug[col]
        inv = 1.0 / aug[col][col]
        for j in range(col, n + 1):
            aug[col][j] *= inv
        for r in range(n):
            if r != col and aug[r][col]:
                fac = aug[r][col]
                for j in range(col, n + 1):
                    aug[r][j] -= fac * aug[col][j]
    return [aug[i][n] for i in range(n)]


def _rodrigues(w: Sequence[float]) -> list[list[float]]:
    wx, wy, wz = w[0], w[1], w[2]
    th = math.sqrt(wx * wx + wy * wy + wz * wz)
    if th < 1e-8:
        return [[1.0, -wz, wy], [wz, 1.0, -wx], [-wy, wx, 1.0]]
    ux, uy, uz = wx / th, wy / th, wz / th
    c, s, one_c = math.cos(th), math.sin(th), 1.0 - math.cos(th)
    return [
        [c + ux * ux * one_c, ux * uy * one_c - uz * s, ux * uz * one_c + uy * s],
        [uy * ux * one_c + uz * s, c + uy * uy * one_c, uy * uz * one_c - ux * s],
        [uz * ux * one_c - uy * s, uz * uy * one_c + ux * s, c + uz * uz * one_c],
    ]


def _mat3_mul(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _polar_so3(r1: Sequence[float], r2: Sequence[float]) -> tuple[list[float], list[float], list[float]]:
    """Closest orthonormal basis [r1, r2, r3] in SO(3) via exact 2x2 polar decomposition."""
    a = sum(x * x for x in r1)
    b = sum(x * y for x, y in zip(r1, r2))
    c = sum(y * y for y in r2)
    phi = 0.5 * math.atan2(2.0 * b, a - c)
    cp, sp = math.cos(phi), math.sin(phi)
    l1 = max(1e-12, a * cp * cp + 2.0 * b * cp * sp + c * sp * sp)
    l2 = max(1e-12, a * sp * sp - 2.0 * b * cp * sp + c * cp * cp)
    i1, i2 = 1.0 / math.sqrt(l1), 1.0 / math.sqrt(l2)
    m00 = i1 * cp * cp + i2 * sp * sp
    m01 = (i1 - i2) * cp * sp
    m11 = i1 * sp * sp + i2 * cp * cp
    o1 = [r1[i] * m00 + r2[i] * m01 for i in range(3)]
    o2 = [r1[i] * m01 + r2[i] * m11 for i in range(3)]
    o3 = [o1[1] * o2[2] - o1[2] * o2[1], o1[2] * o2[0] - o1[0] * o2[2], o1[0] * o2[1] - o1[1] * o2[0]]
    return o1, o2, o3


def _decompose_se3(h_m2u: Sequence[float], k: Sequence[Sequence[float]], centroid: Point):
    k_flat = [v for row in k for v in row]
    b = _matmul3(_invert3(k_flat), h_m2u)
    b1, b2, b3 = [b[0], b[3], b[6]], [b[1], b[4], b[7]], [b[2], b[5], b[8]]
    n1, n2 = math.sqrt(sum(v * v for v in b1)), math.sqrt(sum(v * v for v in b2))
    if n1 < 1e-12 or n2 < 1e-12:
        raise ValueError("degenerate pose columns")
    dot12 = sum(x * y for x, y in zip(b1, b2))
    ortho_err = max(abs(n1 / n2 - 1.0), abs(dot12 / (n1 * n2)))
    s = 0.5 * (n1 + n2)
    r1, r2, t = [v / s for v in b1], [v / s for v in b2], [v / s for v in b3]
    mx, my = centroid
    if r1[2] * mx + r2[2] * my + t[2] < 0.0:
        r1, r2, t = [-v for v in r1], [-v for v in r2], [-v for v in t]
    o1, o2, o3 = _polar_so3(r1, r2)
    rot = [[o1[r], o2[r], o3[r]] for r in range(3)]
    return rot, t, ortho_err


def _refine_se3(rot: list[list[float]], t: list[float], map_pts: Sequence[Point],
                raw_pts: Sequence[Point], profile: Mapping[str, Any]) -> tuple[list[list[float]], list[float]]:
    k, d, model = profile["K"], profile["D"], profile["model"]
    fx, fy, cx, cy = k[0][0], k[1][1], k[0][2], k[1][2]
    delta = 6.0
    eps = [1e-5, 1e-5, 1e-5, 1e-4, 1e-4, 1e-4]

    def _res(r_mat, t_vec):
        out = []
        for (mx, my), (u, v) in zip(map_pts, raw_pts):
            zc = r_mat[2][0] * mx + r_mat[2][1] * my + t_vec[2]
            if zc <= 1e-4:
                return None
            xc = r_mat[0][0] * mx + r_mat[0][1] * my + t_vec[0]
            yc = r_mat[1][0] * mx + r_mat[1][1] * my + t_vec[1]
            xd, yd = distort_normalized(xc / zc, yc / zc, model, d)
            out.append(xd * fx + cx - u)
            out.append(yd * fy + cy - v)
        return out

    def _huber(res):
        return sum(0.5 * r * r if abs(r) <= delta else delta * (abs(r) - 0.5 * delta) for r in res)

    lam = 1e-3
    r0 = _res(rot, t)
    if r0 is None:
        return rot, t
    for _ in range(25):
        cost0 = _huber(r0)
        m = len(r0)
        cols = []
        for j in range(6):
            xi = [0.0] * 6
            xi[j] = eps[j]
            rj = _res(_mat3_mul(_rodrigues(xi[:3]), rot), [t[0] + xi[3], t[1] + xi[4], t[2] + xi[5]])
            if rj is None:
                cols = None
                break
            cols.append([(rj[i] - r0[i]) / eps[j] for i in range(m)])
        if cols is None:
            break
        weights = [1.0 if abs(r) <= delta else delta / (abs(r) + 1e-9) for r in r0]
        jtwj = [[0.0] * 6 for _ in range(6)]
        jtwr = [0.0] * 6
        for i in range(m):
            wi = weights[i]
            ri = r0[i]
            for a in range(6):
                wa = wi * cols[a][i]
                jtwr[a] += -wa * ri
                for b in range(a, 6):
                    jtwj[a][b] += wa * cols[b][i]
        for a in range(6):
            for b in range(a):
                jtwj[a][b] = jtwj[b][a]
            jtwj[a][a] += lam * max(1e-8, jtwj[a][a])
        try:
            step = _solve_linear(jtwj, jtwr)
        except ValueError:
            lam *= 10.0
            continue
        r_cand = _mat3_mul(_rodrigues(step[:3]), rot)
        t_cand = [t[0] + step[3], t[1] + step[4], t[2] + step[5]]
        r1 = _res(r_cand, t_cand)
        if r1 is not None and _huber(r1) < cost0:
            rot, t, r0 = r_cand, t_cand, r1
            lam = max(1e-6, lam * 0.3)
            if max(abs(s) for s in step) < 1e-7:
                break
        else:
            lam = min(1e4, lam * 5.0)
            if lam >= 1e4:
                break
    return rot, t


def _apply3(h: Sequence[float], x: float, y: float) -> Point:
    w = h[6] * x + h[7] * y + h[8]
    if abs(w) < 1e-12:
        raise ValueError("homography w is zero")
    return (h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w


def _hull_area(pts: Sequence[Point]) -> float:
    uniq = sorted(set(pts))
    if len(uniq) < 3:
        return 0.0
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower: list[Point] = []
    for p in uniq:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0.0:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(uniq):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0.0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    area = 0.0
    for i in range(len(hull)):
        x0, y0 = hull[i]
        x1, y1 = hull[(i + 1) % len(hull)]
        area += x0 * y1 - x1 * y0
    return abs(area) * 0.5


def solve_planar_pose(
    image_pts: Sequence[Point],
    map_pts: Sequence[Point],
    *,
    image_size: Sequence[int],
    lens_profile: Mapping[str, Any] | None = None,
    hfov_deg: float | None = None,
    track_bounds_m: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Solve planar floor mapping (SE(3) when calibrated lens is given, else normalized DLT) + quality gates."""
    if len(image_pts) != len(map_pts) or len(image_pts) < 4:
        raise ValueError("at least four point correspondences are required")
    w, h_img = int(image_size[0]), int(image_size[1])
    raw_pts = [(float(u), float(v)) for u, v in image_pts]
    world_pts = [(float(x), float(y)) for x, y in map_pts]
    profile = scale_lens_profile(lens_profile, (w, h_img)) if lens_profile is not None else None
    undist_pts = [undistort_point(u, v, profile) for u, v in raw_pts] if profile is not None else raw_pts

    h_m2u = fit_homography_dlt(world_pts, undist_pts)
    mx = sum(p[0] for p in world_pts) / len(world_pts)
    my = sum(p[1] for p in world_pts) / len(world_pts)
    wc = h_m2u[6] * mx + h_m2u[7] * my + h_m2u[8]
    if wc < 0.0:
        h_m2u = [-v for v in h_m2u]

    warnings: list[str] = []
    camera_pose_m: list[float] | None = None
    ortho_error: float | None = None
    k_diag = profile["K"] if profile is not None else (
        default_lens_profile(w, h_img, hfov_deg)["K"] if hfov_deg is not None else None
    )

    if k_diag is not None:
        try:
            rot, t_vec, ortho_error = _decompose_se3(h_m2u, k_diag, (mx, my))
            if profile is not None:
                rot, t_vec = _refine_se3(rot, t_vec, world_pts, raw_pts, profile)
                h_phys = [
                    rot[0][0], rot[0][1], t_vec[0],
                    rot[1][0], rot[1][1], t_vec[1],
                    rot[2][0], rot[2][1], t_vec[2],
                ]
                h_m2u = _matmul3([v for row in k_diag for v in row], h_phys)
                if abs(h_m2u[8]) > 1e-12:
                    h_m2u = [v / h_m2u[8] for v in h_m2u]
            cam = [-(rot[0][r] * t_vec[0] + rot[1][r] * t_vec[1] + rot[2][r] * t_vec[2]) for r in range(3)]
            camera_pose_m = [round(cam[0], 4), round(cam[1], 4), round(abs(cam[2]), 4)]
        except ValueError:
            warnings.append("camera_pose_unavailable")

    h_u2m = _invert3(h_m2u)
    residuals: list[dict[str, float]] = []
    errs_m: list[float] = []
    reproj_sq = 0.0
    for (u_raw, v_raw), (u_un, v_un), (x_gt, y_gt) in zip(raw_pts, undist_pts, world_pts):
        x_p, y_p = _apply3(h_u2m, u_un, v_un)
        dx, dy = x_p - x_gt, y_p - y_gt
        err_m = math.hypot(dx, dy)
        errs_m.append(err_m)
        u_pred, v_pred = _apply3(h_m2u, x_gt, y_gt)
        if profile is not None:
            u_pred, v_pred = distort_point(u_pred, v_pred, profile)
        reproj_sq += (u_pred - u_raw) ** 2 + (v_pred - v_raw) ** 2
        residuals.append({"dx_m": round(dx, 5), "dy_m": round(dy, 5), "err_m": round(err_m, 5)})

    n = len(errs_m)
    sorted_errs = sorted(errs_m)
    rms_m = math.sqrt(sum(e * e for e in errs_m) / n)
    p95_m = sorted_errs[min(n - 1, int(math.ceil(0.95 * n)) - 1)]
    max_m = sorted_errs[-1]
    reproj_rms_px = math.sqrt(reproj_sq / n)

    if track_bounds_m is not None:
        bx0, by0, bx1, by1 = [float(v) for v in track_bounds_m]
    else:
        xs, ys = [p[0] for p in world_pts], [p[1] for p in world_pts]
        bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
    bcx, bcy = 0.5 * (bx0 + bx1), 0.5 * (by0 + by1)
    quads = {(1 if x >= bcx else 0, 1 if y >= bcy else 0) for x, y in world_pts}
    quadrant_coverage = len(quads)
    bounds_area = max(1e-6, (bx1 - bx0) * (by1 - by0))
    hull_frac = _hull_area(world_pts) / bounds_area

    weights = [h_m2u[6] * x + h_m2u[7] * y + h_m2u[8] for x in (bx0, bx1) for y in (by0, by1)]
    horizon_inside = any(abs(wt) <= 1e-9 for wt in weights) or not (all(wt > 0 for wt in weights) or all(wt < 0 for wt in weights))

    accepted = True
    reason = "ok"
    if horizon_inside:
        accepted, reason = False, "horizon_inside_track_bounds"
    elif hull_frac < 1e-4:
        accepted, reason = False, "collinear_points"
    elif camera_pose_m is not None and not (MIN_CAMERA_HEIGHT_M <= camera_pose_m[2] <= MAX_CAMERA_HEIGHT_M):
        accepted, reason = False, "camera_height_out_of_range"
    elif ortho_error is not None and ortho_error > (0.25 if profile is not None else 0.45):
        accepted, reason = False, "excessive_shear"
    elif rms_m > 0.06 or (n >= 5 and max_m > 0.15):
        accepted, reason = False, "high_reprojection_error"

    if quadrant_coverage < 3:
        warnings.append("narrow_quadrant_coverage")
    if hull_frac < 0.15:
        warnings.append("small_convex_hull")
    if ortho_error is not None and profile is None and ortho_error > 0.15:
        warnings.append("high_shear_or_fov_mismatch")

    fit_score = max(0.0, min(1.0, math.exp(-rms_m / 0.05)))
    return {
        "accepted": accepted,
        "reason": reason,
        "map_to_image": [round(v, 10) for v in h_m2u],
        "image_to_map": [round(v, 10) for v in h_u2m],
        "lens_profile": profile,
        "residuals_m": residuals,
        "rms_m": round(rms_m, 5),
        "p95_m": round(p95_m, 5),
        "max_m": round(max_m, 5),
        "reproj_rms_px": round(reproj_rms_px, 3),
        "camera_pose_m": camera_pose_m,
        "ortho_error": None if ortho_error is None else round(ortho_error, 4),
        "quadrant_coverage": quadrant_coverage,
        "hull_area_frac": round(hull_frac, 4),
        "fit_score": round(fit_score, 4),
        "warnings": warnings,
    }


def project_pixel_to_plane(
    u: float,
    v: float,
    image_to_map: Sequence[float],
    *,
    height_m: float = 0.0,
    lens_profile: Mapping[str, Any] | None = None,
    camera_pose: Sequence[float] | None = None,
) -> Point:
    """Undistort pixel ``(u, v)``, project to ``z=0``, and apply height parallax toward nadir."""
    ux, uy = undistort_point(u, v, lens_profile) if lens_profile is not None else (float(u), float(v))
    x, y = _apply3(image_to_map, ux, uy)
    if height_m > 0.0 and camera_pose is not None:
        cx, cy, cam_h = float(camera_pose[0]), float(camera_pose[1]), float(camera_pose[2])
        if height_m >= cam_h:
            raise ValueError("object height must be below camera")
        keep = (cam_h - height_m) / cam_h
        x = cx + (x - cx) * keep
        y = cy + (y - cy) * keep
    return x, y
