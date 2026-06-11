from compas.geometry import Box, Frame, Point, Vector
from compas_timber.fabrication import LapProxy


def _to_compas_point(pt):
    # Already a COMPAS Point — return unchanged.
    if isinstance(pt, Point):
        return pt
    # Rhino Point3d — uppercase coordinates.
    try:
        return Point(float(pt.X), float(pt.Y), float(pt.Z))
    except AttributeError:
        pass
    # List, tuple, or any sequence [x, y, z].
    try:
        return Point(float(pt[0]), float(pt[1]), float(pt[2]))
    except (TypeError, KeyError, IndexError):
        pass
    raise TypeError("Cannot convert {} (type {}) to COMPAS Point".format(pt, type(pt).__name__))


def _coords(obj):
    # Return (x, y, z) as plain floats from any COMPAS Point/Vector.
    # Uses index access to avoid .x/.y/.z attribute chain issues.
    return float(obj[0]), float(obj[1]), float(obj[2])


def _distance_point_to_line(pt, line):
    # Project pt onto the line segment and return the distance.
    sx, sy, sz = _coords(line.start)
    ex, ey, ez = _coords(line.end)
    px, py, pz = _coords(pt)
    dx, dy, dz = ex - sx, ey - sy, ez - sz
    qx, qy, qz = px - sx, py - sy, pz - sz
    t = (qx * dx + qy * dy + qz * dz) / (dx * dx + dy * dy + dz * dz + 1e-16)
    t = max(0.0, min(1.0, t))
    cx, cy, cz = sx + t * dx, sy + t * dy, sz + t * dz
    return ((px - cx) ** 2 + (py - cy) ** 2 + (pz - cz) ** 2) ** 0.5


def _normalise_beams(base_beams):
    # Accept TimberModelCategoryView (.beams), any model with .elements, or a plain list.
    if hasattr(base_beams, "beams"):
        return list(base_beams.beams)
    if hasattr(base_beams, "elements"):
        return list(base_beams.elements)
    return list(base_beams)


def create_base_beam_plates_from_points(
    base_beams,
    points,
    plate_size=(0.100, 0.140, 0.015),
    beam_width=None,
):
    """
    Return a list of (Box, beam, contact_normal) for each metal plate.

    For each point (on a base beam centerline), the closest beam is found
    and two plates are created — one on each side face of the beam
    (+ and - yaxis).  The plate Box straddles the beam face: half its
    thickness sits inside the beam (pocket volume), half sits outside
    (visible metal plate).

    Parameters
    ----------
    base_beams : list of compas_timber.elements.Beam
        Already-filtered list of base beams from the timber model.
    points : list of compas.geometry.Point
        Centerline points of the base beams.  Each point is matched to its
        owning beam by minimum distance.
    plate_size : tuple(float, float, float)
        (x, y, z) dimensions of the plate Box in metres.
        x = along beam centerline, y = along beam height (zaxis), z = plate thickness.
        Default: 100 x 140 x 15 mm.
    beam_width : float or None
        Cross-section width of the base beam in metres used to offset the
        plate origin to the side face.  If None (default), beam.width is used
        automatically so the offset is always exact.

    Returns
    -------
    list of tuple
        Each entry is (compas.geometry.Box, beam, contact_normal).
        contact_normal points from the plate face into the beam.
    """
    _beams = _normalise_beams(base_beams)

    # If GH expanded COMPAS Points into raw coordinates, regroup them.
    _pts = list(points)
    if _pts and isinstance(_pts[0], (int, float)):
        if len(_pts) % 3 != 0:
            raise ValueError(
                "points looks like a flat coordinate list but has {} elements "
                "(not divisible by 3).".format(len(_pts))
            )
        _pts = [
            Point(float(_pts[i]), float(_pts[i + 1]), float(_pts[i + 2]))
            for i in range(0, len(_pts), 3)
        ]

    results = []

    for pt in _pts:
        pt = _to_compas_point(pt)
        best_beam = None
        best_dist = float("inf")

        for beam in _beams:
            dist = _distance_point_to_line(pt, beam.centerline)
            if dist < best_dist:
                best_dist = dist
                best_beam = beam

        if best_beam is None:
            continue

        # normal = yaxis  → offsets to the two side faces
        # plate y-dir = zaxis  → plate runs along beam height
        nx, ny, nz = _coords(best_beam.frame.yaxis)
        xx, xy, xz = _coords(best_beam.frame.xaxis)
        zx, zy, zz = _coords(best_beam.frame.zaxis)
        px, py, pz = _coords(pt)

        xaxis = Vector(xx, xy, xz)
        zaxis = Vector(zx, zy, zz)

        w = beam_width if beam_width is not None else best_beam.width
        thickness = plate_size[2]
        for side in [1, -1]:
            # Offset so the outer face is flush with the beam surface;
            # the full plate thickness sits inside the beam.
            s = side * (w / 2 - thickness / 2)
            origin = Point(px + nx * s, py + ny * s, pz + nz * s)
            plate_frame = Frame(origin, xaxis, zaxis)
            contact_normal = Vector(-nx * side, -ny * side, -nz * side)
            results.append(
                (Box(*plate_size, frame=plate_frame), best_beam, contact_normal)
            )

    return results


def apply_laps_single_beam(compas_breps, beams):
    """
    Apply a Lap feature to each beam at its plate location.

    Parameters
    ----------
    compas_breps : list of compas.geometry.Brep
        One COMPAS Brep per plate, already converted from the Rhino geometry.
    beams : list of compas_timber.elements.Beam
        Parallel list matching compas_breps — one beam per plate.

    Returns
    -------
    list of (LapProxy, beam)
        All lap/beam pairs that were successfully created.
    """
    lap_beam_pairs = []

    for brep, beam in zip(compas_breps, beams):
        try:
            lap = LapProxy.from_volume_and_beam(brep, beam)
            beam.add_feature(lap)
            lap_beam_pairs.append((lap, beam))
            print("  Lap added")
        except Exception as e:
            print(f"  Warning lap: {e}")

    return lap_beam_pairs
