
# venv: ca-fs26-focus-work

from compas_rhino.devtools import DevTools
DevTools.ensure_path()
ghenv.Component.Message = "Enforce Arch Planarity"

# -------------------- IMPORTS ---------------------

import math
from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import Plane

# ------------------- DEFAULTS ---------------------

if 'arch_categories_A' not in dir():  arch_categories_A = ["arch_A"]
if 'arch_categories_B' not in dir():  arch_categories_B = ["arch_B"]
if 'tolerance' not in dir():          tolerance = 0.001
if 'run' not in dir():                run = True

# ------------------- VALIDATION -------------------

if rf_system is None:
    raise ValueError("rf_system input is required.")

# ------------------- HELPERS ----------------------

def _collect_points_for_categories(mesh, categories):
    """Return list of (edge, 'start'/'end', Point) for all edges matching categories."""
    cat_set = set(categories)
    entries = []
    for edge in mesh.edges():
        cat = mesh.edge_attribute(edge, "beam_category")
        if cat not in cat_set:
            continue
        cl = mesh.edge_attribute(edge, "centerline")
        if cl is None:
            continue
        entries.append((edge, "start", Point(*cl.start)))
        entries.append((edge, "end",   Point(*cl.end)))
    return entries


def _best_fit_plane(points):
    """Fit a plane to points via PCA (SVD). Returns Plane(origin, normal)."""
    n = len(points)
    if n < 3:
        return None

    cx = sum(p.x for p in points) / n
    cy = sum(p.y for p in points) / n
    cz = sum(p.z for p in points) / n
    centroid = Point(cx, cy, cz)

    # Build covariance matrix
    cov = [[0.0, 0.0, 0.0],
           [0.0, 0.0, 0.0],
           [0.0, 0.0, 0.0]]
    for p in points:
        d = [p.x - cx, p.y - cy, p.z - cz]
        for i in range(3):
            for j in range(3):
                cov[i][j] += d[i] * d[j]

    # Power iteration to find smallest eigenvector (normal to best-fit plane)
    # We find the largest two eigenvectors first, then take the cross product.
    # Simpler: use the eigenvector of the smallest eigenvalue via Jacobi / direct SVD.
    # For 3x3 symmetric matrices, use the analytical approach via numpy if available,
    # otherwise fall back to a simple iterative method.
    try:
        import System.Array as SA
        import System.Double as SD
        raise ImportError  # force numpy path
    except Exception:
        pass

    try:
        import numpy as np
        mat = np.array(cov)
        _, vecs = np.linalg.eigh(mat)  # eigenvalues ascending
        normal = Vector(float(vecs[0, 0]), float(vecs[1, 0]), float(vecs[2, 0]))
    except ImportError:
        # Fallback: cross product of two principal directions (good enough for near-planar sets)
        # Find the two points furthest from the centroid
        def dist2(p):
            return (p.x-cx)**2 + (p.y-cy)**2 + (p.z-cz)**2
        sorted_pts = sorted(points, key=dist2, reverse=True)
        v1 = Vector(sorted_pts[0].x - cx, sorted_pts[0].y - cy, sorted_pts[0].z - cz)
        v2 = Vector(sorted_pts[1].x - cx, sorted_pts[1].y - cy, sorted_pts[1].z - cz)
        normal = v1.cross(v2)

    normal.unitize()
    return Plane(centroid, normal)


def _project_point_to_plane(point, plane):
    """Project a point onto a plane."""
    d = (point.x - plane.point.x) * plane.normal.x + \
        (point.y - plane.point.y) * plane.normal.y + \
        (point.z - plane.point.z) * plane.normal.z
    return Point(
        point.x - d * plane.normal.x,
        point.y - d * plane.normal.y,
        point.z - d * plane.normal.z,
    )


def _point_plane_distance(point, plane):
    return abs(
        (point.x - plane.point.x) * plane.normal.x +
        (point.y - plane.point.y) * plane.normal.y +
        (point.z - plane.point.z) * plane.normal.z
    )


def _enforce_planarity(mesh, categories, label, tol):
    entries = _collect_points_for_categories(mesh, categories)
    if not entries:
        print("{}: no edges found for categories {}".format(label, categories))
        return 0, None, []

    points = [e[2] for e in entries]
    plane = _best_fit_plane(points)
    if plane is None:
        print("{}: not enough points to fit a plane".format(label))
        return 0, None, []

    # Measure residuals before
    residuals = [_point_plane_distance(p, plane) for p in points]
    max_before = max(residuals)
    rms_before = math.sqrt(sum(r*r for r in residuals) / len(residuals))
    print("{}: {} points, RMS={:.4f}m, max={:.4f}m before correction".format(
        label, len(points), rms_before, max_before))

    if not run:
        return 0, plane, residuals

    # Project and write back
    moved_count = 0
    outliers = []
    for edge, end_key, point in entries:
        dist = _point_plane_distance(point, plane)
        if dist <= tol:
            continue
        projected = _project_point_to_plane(point, plane)
        cl = mesh.edge_attribute(edge, "centerline")
        if end_key == "start":
            new_cl = Line(projected, cl.end)
        else:
            new_cl = Line(cl.start, projected)
        mesh.edge_attribute(edge, "centerline", new_cl)
        moved_count += 1
        outliers.append((edge, end_key, dist))

    # Measure residuals after
    entries_after = _collect_points_for_categories(mesh, categories)
    points_after = [e[2] for e in entries_after]
    residuals_after = [_point_plane_distance(p, plane) for p in points_after]
    rms_after = math.sqrt(sum(r*r for r in residuals_after) / len(residuals_after))
    print("{}: corrected {} endpoints, RMS={:.6f}m after".format(label, moved_count, rms_after))

    return moved_count, plane, outliers

# ------------------- MAIN -------------------------

mesh = rf_system.mesh

cats_A = list(arch_categories_A) if hasattr(arch_categories_A, '__iter__') and not isinstance(arch_categories_A, str) else [arch_categories_A]
cats_B = list(arch_categories_B) if hasattr(arch_categories_B, '__iter__') and not isinstance(arch_categories_B, str) else [arch_categories_B]

moved_A, plane_A, outliers_A = _enforce_planarity(mesh, cats_A, "arch_A", float(tolerance))
moved_B, plane_B, outliers_B = _enforce_planarity(mesh, cats_B, "arch_B", float(tolerance))

total_moved = moved_A + moved_B
print("Total endpoints corrected: {}".format(total_moved))

# ------------------- OUTPUT -----------------------

corrected = total_moved
fit_plane_A = plane_A
fit_plane_B = plane_B
