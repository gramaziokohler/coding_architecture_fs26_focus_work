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
    use_llap_joint=False,
    arch_beam_height=0.10,
    arch_plate=(0.046, 0.111, 0.0025),
    base_beam_height=0.14,
    base_plate=(0.051, 0.191, 0.0025),
):
    """
    Return a list of plate data tuples for each metal plate at every LMiterJoint.

    Each tuple contains:
        (visual_box, beam_a, beam_b, contact_normal, lap_box_a, lap_box_b)

    - visual_box  : Box at the averaged joint normal — used for the metal_plates output.
    - lap_box_a   : Box positioned at beam_a's own side face — used for beam_a's pocket.
    - lap_box_b   : Box positioned at beam_b's own side face — used for beam_b's pocket.

    Using per-beam lap boxes ensures both pockets land on the correct face regardless
    of the angle between the two beams (important for inclined arch joints).

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

        cat_a = getattr(beam_a, "attributes", {}).get("category", "inner")
        cat_b = getattr(beam_b, "attributes", {}).get("category", "inner")
        is_base_joint = cat_a == "base" or cat_b == "base"

        # LLap joint: no metal plates on base beams.
        # LMiter joint (use_llap_joint=False): include base beam joints.
        # Non-base arch joints: always included regardless of toggle.
        # Skip base beam joints when toggle is LLap; include them for LMiter.
        if is_base_joint and use_llap_joint:
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

        def _project_off_bisector(vec):
            dot = vec.x * bisector.x + vec.y * bisector.y + vec.z * bisector.z
            return Vector(
                vec.x - dot * bisector.x,
                vec.y - dot * bisector.y,
                vec.z - dot * bisector.z,
            )

        if is_base_joint:
            # Base beams are horizontal. Their local zaxis points sideways in this
            # model, so we use world Z directly to get flat top/bottom plates.
            normal = Vector(0.0, 0.0, 1.0)
        else:
            avg_z = Vector(*beam_a.frame.zaxis) + Vector(*beam_b.frame.zaxis)
            avg_z.unitize()
            normal = _project_off_bisector(avg_z)

            if normal.length < 0.01:
                avg_y = Vector(*beam_a.frame.yaxis) + Vector(*beam_b.frame.yaxis)
                avg_y.unitize()
                normal = _project_off_bisector(avg_y)

            normal.unitize()

        # Select plate dimensions and fallback beam width.
        if _is_arch_joint(beam_a, beam_b):
            fallback_width = arch_beam_height
            plate_size = arch_plate
        else:
            fallback_width = base_beam_height
            plate_size = base_plate

        plate_thickness = plate_size[2]

        def _lap_box(beam, side):
            if is_base_joint:
                # Use same world-Z direction as the visual plate so pockets land
                # on the top/bottom surfaces, not the side faces.
                bn = normal
                bw = fallback_width
            else:
                bn = _project_off_bisector(Vector(*beam.frame.yaxis))
                if bn.length < 0.01:
                    bn = normal
                else:
                    bn.unitize()
                try:
                    bw = beam.width
                except AttributeError:
                    bw = fallback_width
            f = Frame.from_plane(Plane(joint_pt, bn))
            f.translate(bn * side * (bw / 2 - plate_thickness / 2))
            f.yaxis = f.zaxis.cross(bisector)
            f.xaxis = bisector
            return Box(*plate_size, frame=f)

        for side in [1, -1]:
            # Visual plate at the averaged normal position.
            if is_base_joint:
                # Use the beam height parameter (Z-dimension) for top/bottom offset.
                avg_width = fallback_width
            else:
                try:
                    avg_width = (beam_a.width + beam_b.width) / 2
                except AttributeError:
                    avg_width = fallback_width
            plate_frame = Frame.from_plane(Plane(joint_pt, normal))
            plate_frame.translate(normal * side * (avg_width / 2 - plate_thickness / 2))
            plate_frame.yaxis = plate_frame.zaxis.cross(bisector)
            plate_frame.xaxis = bisector
            visual_box = Box(*plate_size, frame=plate_frame)

            # Per-beam lap boxes — each positioned at that beam's own side face.
            lap_box_a = _lap_box(beam_a, side)
            lap_box_b = _lap_box(beam_b, side)

            contact_normal = Vector(
                -normal.x * side, -normal.y * side, -normal.z * side
            )

            results.append(
                (visual_box, beam_a, beam_b, contact_normal, lap_box_a, lap_box_b)
            )

    return results


def apply_laps(brep_beam_pairs):
    """
    Apply a LapProxy feature to each (brep, beam) pair.

    Parameters
    ----------
    brep_beam_pairs : list of (compas.geometry.Brep, beam)
        Each entry is a plate brep and the specific beam it should cut into.
        beam_a and beam_b each get their own correctly-positioned brep.

    Returns
    -------
    list of (LapProxy, beam)
    """
    lap_beam_pairs = []

    for brep, beam in brep_beam_pairs:
        try:
            lap = LapProxy.from_volume_and_beam(brep, beam)
            beam.add_feature(lap)
            lap_beam_pairs.append((lap, beam))
            print("  Lap added")
        except Exception as e:
            print(f"  Warning lap: {e}")

    return lap_beam_pairs
