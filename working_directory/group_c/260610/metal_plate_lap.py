from compas.geometry import Box, Frame, Vector, Plane
from compas_timber.connections import LMiterJoint
from compas_timber.fabrication import LapProxy

_ARCH_INCLINATION_THRESHOLD = 0.15


def _is_arch_joint(beam_a, beam_b):
    """Return True when either beam is inclined (arch); used only for dimension selection."""

    def inclination(beam):
        return abs(beam.centerline.direction.unitized().z)

    return (
        inclination(beam_a) > _ARCH_INCLINATION_THRESHOLD
        or inclination(beam_b) > _ARCH_INCLINATION_THRESHOLD
    )


def create_metal_plates(
    timber_model,
    arch_beam_height=0.10,
    arch_plate=(0.046, 0.111, 0.0025),
    base_beam_height=0.14,
    base_plate=(0.051, 0.191, 0.0025),
):
    """
    Return a list of (Box, beam_a, beam_b) for each metal plate at every LMiterJoint.

    The plate frame is computed with one unified code path for all joint types:
    the averaged beam zaxis is projected onto the plane perpendicular to the
    bisector, which works correctly for both horizontal base beams and inclined
    arch beams without any separate branch.  Arch / base detection is used only
    to select the appropriate plate dimensions and beam height.

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
        Each entry is (compas.geometry.Box, beam_a, beam_b).
    """
    results = []

    if timber_model is None:
        return results

    for joint in timber_model.joints:
        if not isinstance(joint, LMiterJoint):
            continue

        beam_a = joint.beam_a
        beam_b = joint.beam_b
        if beam_a is None or beam_b is None:
            continue

        joint_pt = joint.location
        if joint_pt is None:
            continue

        # Build bisector from flipped beam x-axes so it always points away from the corner.
        vA = Vector(*beam_a.frame.xaxis)
        vB = Vector(*beam_b.frame.xaxis)
        tA, _ = beam_a.endpoint_closest_to_point(joint_pt)
        if tA == "end":
            vA *= -1.0
        tB, _ = beam_b.endpoint_closest_to_point(joint_pt)
        if tB == "end":
            vB *= -1.0

        bisector = vA + vB
        bisector.unitize()

        # Unified plate normal: project the averaged beam zaxis onto the plane ⊥ bisector.
        # This works for base beams (zaxis already ⊥ bisector → projection = identity)
        # and most arch joints. Falls back to yaxis when zaxis ≈ ±bisector (apex joints)
        # because the projection cancels to near-zero in that case.
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
            # zaxis is nearly parallel or anti-parallel to bisector (e.g. arch apex).
            # Use yaxis instead — it is always perpendicular to the beam length.
            avg_y = Vector(*beam_a.frame.yaxis) + Vector(*beam_b.frame.yaxis)
            avg_y.unitize()
            normal = _project_off_bisector(avg_y)

        normal.unitize()

        # Select dimensions only — frame computation above is the same for all joints.
        if _is_arch_joint(beam_a, beam_b):
            beam_height = arch_beam_height
            plate_size = arch_plate
        else:
            beam_height = base_beam_height
            plate_size = base_plate

        plate_thickness = plate_size[2]

        for side in [1, -1]:
            plate_frame = Frame.from_plane(Plane(joint_pt, normal))
            # Shift inward by half the plate thickness so the outer face is flush
            # with the beam's top surface rather than sitting proud of it.
            plate_frame.translate(normal * side * (beam_height / 2 - plate_thickness / 2))
            plate_frame.yaxis = plate_frame.zaxis.cross(bisector)
            plate_frame.xaxis = bisector

            # Contact face points toward the beam: opposite to the offset direction.
            contact_normal = Vector(
                -normal.x * side, -normal.y * side, -normal.z * side
            )

            results.append(
                (Box(*plate_size, frame=plate_frame), beam_a, beam_b, contact_normal)
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
