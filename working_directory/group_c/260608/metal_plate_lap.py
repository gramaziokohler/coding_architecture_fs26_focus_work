from compas.geometry import Box, Frame, Vector, Plane, Point, distance_point_point
from compas_timber.connections import LMiterJoint
from compas_timber.fabrication import LapProxy

_ARCH_INCLINATION_THRESHOLD = 0.15
_ARCH_CATS = frozenset({"arch", "arch_A", "arch_B"})


def _is_arch_joint(beam_a, beam_b):
    """Return True when either beam is inclined (arch); used only for dimension selection."""

    def inclination(beam):
        return abs(beam.centerline.direction.unitized().z)

    return (
        inclination(beam_a) > _ARCH_INCLINATION_THRESHOLD
        or inclination(beam_b) > _ARCH_INCLINATION_THRESHOLD
    )


def _joint_location_from_beams(beam_a, beam_b):
    """Midpoint between the two closest beam endpoints — fallback when joint.location is None.

    For inclined 3D beams the centerline extensions are often skew (non-intersecting),
    so joint.location returns None.  Using the closest endpoint pair gives a good
    approximation of the physical connection point.
    """
    la = beam_a.centerline
    lb = beam_b.centerline
    best_dist = None
    best_pt = None
    for pa in [la.start, la.end]:
        for pb in [lb.start, lb.end]:
            d = distance_point_point(pa, pb)
            if best_dist is None or d < best_dist:
                best_dist = d
                best_pt = Point(
                    (pa.x + pb.x) / 2.0,
                    (pa.y + pb.y) / 2.0,
                    (pa.z + pb.z) / 2.0,
                )
    return best_pt


def create_metal_plates(
    timber_model,
    arch_beam_height=0.10,
    arch_plate=(0.046, 0.111, 0.0025),
    base_beam_height=0.14,
    base_plate=(0.051, 0.191, 0.0025),
):
    """
    Return a list of (Box, beam_a, beam_b, contact_normal) for each metal plate.

    Joints processed:
    - LMiterJoint — base-base and arch-arch corner joints (original behaviour).
    - Any joint connecting an arch beam to a base beam regardless of joint type
      (e.g. PreferredFaceTButtJoint / TButtJoint at arch feet).

    Inner-beam joints are excluded.
    joint.location falling back to midpoint-of-closest-endpoints when None
    (happens for inclined/skew arch beam pairs).

    Parameters
    ----------
    timber_model : TimberModel
    arch_beam_height : float
        Cross-section height of arch beams in metres.  Default 0.10 m.
    arch_plate : tuple(float, float, float)
        (width, length, thickness) of the arch metal plate in metres.
    base_beam_height : float
        Cross-section height of base/foundation beams in metres.  Default 0.14 m.
    base_plate : tuple(float, float, float)
        (width, length, thickness) of the base metal plate in metres.

    Returns
    -------
    list of tuple
        Each entry is (compas.geometry.Box, beam_a, beam_b, contact_normal).
    """
    results = []

    if timber_model is None:
        return results

    miter_count = 0
    arch_foot_count = 0

    for joint in timber_model.joints:
        beam_a = joint.beam_a
        beam_b = joint.beam_b
        if beam_a is None or beam_b is None:
            continue

        cat_a = beam_a.attributes.get("category", "inner")
        cat_b = beam_b.attributes.get("category", "inner")
        is_arch_a = cat_a in _ARCH_CATS
        is_arch_b = cat_b in _ARCH_CATS

        is_miter = isinstance(joint, LMiterJoint)
        # Non-miter joint where an arch beam connects to a base beam (arch foot).
        is_arch_foot = (
            not is_miter and
            ((is_arch_a and cat_b == "base") or (is_arch_b and cat_a == "base"))
        )

        if not (is_miter or is_arch_foot):
            continue

        # Joint location with fallback (skew 3D lines → joint.location is None).
        joint_pt = getattr(joint, "location", None)
        if joint_pt is None:
            joint_pt = _joint_location_from_beams(beam_a, beam_b)
        if joint_pt is None:
            continue

        if is_miter:
            miter_count += 1
        else:
            arch_foot_count += 1

        print("  {} ({}/{})".format(type(joint).__name__, cat_a, cat_b))

        # ---- plate orientation -----------------------------------------------
        if is_miter:
            # Miter joint: bisector of the two beam axes + projected avg-z as normal.
            vA = Vector(*beam_a.frame.xaxis)
            vB = Vector(*beam_b.frame.xaxis)
            tA, _ = beam_a.endpoint_closest_to_point(joint_pt)
            if tA == "end":
                vA *= -1.0
            tB, _ = beam_b.endpoint_closest_to_point(joint_pt)
            if tB == "end":
                vB *= -1.0

            bisector = vA + vB
            if bisector.length < 0.001:
                bisector = vA.copy()
            bisector.unitize()

            def _project_off_bisector(vec):
                dot = vec.x * bisector.x + vec.y * bisector.y + vec.z * bisector.z
                return Vector(
                    vec.x - dot * bisector.x,
                    vec.y - dot * bisector.y,
                    vec.z - dot * bisector.z,
                )

            avg_z = Vector(*beam_a.frame.zaxis) + Vector(*beam_b.frame.zaxis)
            avg_z.unitize()
            normal = _project_off_bisector(avg_z)

            if normal.length < 0.01:
                # avg_z is (nearly) parallel/anti-parallel to bisector — common at the arch
                # apex where both z-axes point vertically and the bisector also points
                # vertically (downward).  Use avg_z directly: it is the correct face-normal
                # for the arch beams and placing plates along it lands on the beam geometry.
                normal = avg_z.copy()

            if normal.length < 0.001:
                # True degenerate case: fall back to yaxis.
                avg_y = Vector(*beam_a.frame.yaxis) + Vector(*beam_b.frame.yaxis)
                avg_y.unitize()
                normal = _project_off_bisector(avg_y)
                if normal.length < 0.001:
                    normal = avg_y.copy()

            normal.unitize()

        else:
            # Arch foot (non-miter): orient plates on the arch beam's wide face.
            # The bisector is the arch beam axis pointing away from the foot end so the
            # plate faces outward along the arch.  The normal is the arch beam z-axis
            # (perpendicular to the beam's wide face), placing plates on top and bottom.
            arch_beam = beam_a if is_arch_a else beam_b
            vArch = Vector(*arch_beam.frame.xaxis)
            t_arch, _ = arch_beam.endpoint_closest_to_point(joint_pt)
            if t_arch == "end":
                vArch *= -1.0
            bisector = vArch.copy()
            bisector.unitize()

            normal = Vector(*arch_beam.frame.zaxis)
            normal.unitize()

        if normal.length < 0.001:
            print("    Skipped: could not compute plate normal")
            continue

        # ---- select dimensions -----------------------------------------------
        if _is_arch_joint(beam_a, beam_b):
            beam_height = arch_beam_height
            plate_size = arch_plate
        else:
            beam_height = base_beam_height
            plate_size = base_plate

        plate_thickness = plate_size[2]

        for side in [1, -1]:
            plate_frame = Frame.from_plane(Plane(joint_pt, normal))
            plate_frame.translate(normal * side * (beam_height / 2 - plate_thickness / 2))
            plate_frame.yaxis = plate_frame.zaxis.cross(bisector)
            plate_frame.xaxis = bisector

            contact_normal = Vector(
                -normal.x * side, -normal.y * side, -normal.z * side
            )

            results.append(
                (Box(*plate_size, frame=plate_frame), beam_a, beam_b, contact_normal)
            )

    print(
        "create_metal_plates: {} plates ({} miter joints, {} arch feet)".format(
            len(results), miter_count, arch_foot_count
        )
    )
    return results


def apply_laps(compas_breps, beam_pairs):
    """
    Apply Lap features to both beams at each plate location.

    Parameters
    ----------
    compas_breps : list of compas.geometry.Brep
        One COMPAS Brep per plate, already converted from the Rhino geometry.
    beam_pairs : list of (beam_a, beam_b)
        Parallel list matching compas_breps.

    Returns
    -------
    list of (LapProxy, beam)
        All lap/beam pairs that were successfully created, for downstream
        visualisation or export.
    """
    lap_beam_pairs = []

    for brep, (beam_a, beam_b) in zip(compas_breps, beam_pairs):
        for beam, label in [(beam_a, "a"), (beam_b, "b")]:
            try:
                lap = LapProxy.from_volume_and_beam(brep, beam)
                beam.add_feature(lap)
                lap_beam_pairs.append((lap, beam))
                print(f"  Lap added to beam_{label}")
            except Exception as e:
                print(f"  Warning lap_{label}: {e}")

    return lap_beam_pairs
