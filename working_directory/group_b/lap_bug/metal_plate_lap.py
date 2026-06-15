from compas.geometry import Box, Frame, Vector, Plane
from compas_timber.connections import LMiterJoint
from compas_timber.fabrication import Pocket

_ARCH_INCLINATION_THRESHOLD = 0.15
_METAL_PLATE_LAP_TAG = "metal_plate_lap"


def _beam_side_axis(beam, desired_normal):
    """Return the beam cross-section axis closest to ``desired_normal``."""

    candidates = [
        (Vector(*beam.frame.yaxis), getattr(beam, "width", None)),
        (Vector(*beam.frame.zaxis), getattr(beam, "height", None)),
    ]
    desired = Vector(*desired_normal)
    if desired.length:
        desired.unitize()

    best_axis = candidates[0][0]
    best_size = candidates[0][1]
    best_dot = -1.0

    for axis, size in candidates:
        axis = Vector(*axis)
        if not axis.length:
            continue
        axis.unitize()
        dot = abs(axis.dot(desired))
        if dot > best_dot:
            best_axis = axis
            best_size = size
            best_dot = dot

    if best_axis.dot(desired) < 0:
        best_axis *= -1.0

    return best_axis, best_size


def _beam_local_lap_frame(beam, origin, normal, preferred_xaxis=None):
    """Create a BTLx-friendly lap frame aligned to the target beam."""

    lap_zaxis = Vector(*normal)
    lap_zaxis.unitize()

    lap_xaxis = Vector(
        *(preferred_xaxis if preferred_xaxis is not None else beam.frame.xaxis)
    )
    lap_xaxis = lap_xaxis - lap_zaxis * lap_xaxis.dot(lap_zaxis)
    if lap_xaxis.length < 0.01:
        lap_xaxis = Vector(*beam.frame.xaxis)
        lap_xaxis = lap_xaxis - lap_zaxis * lap_xaxis.dot(lap_zaxis)
    lap_xaxis.unitize()

    lap_yaxis = lap_zaxis.cross(lap_xaxis)
    lap_yaxis.unitize()

    return Frame(origin, lap_xaxis, lap_yaxis)


def _rotate_frame_in_plane(frame):
    """Rotate a frame 90 degrees around its normal without moving its origin."""

    return Frame(frame.point, frame.yaxis, frame.xaxis * -1.0)


def _mark_metal_plate_lap(feature):
    try:
        feature.__dict__["_metal_plate_lap_source"] = _METAL_PLATE_LAP_TAG
    except Exception:
        pass


def _is_metal_plate_lap(feature):
    try:
        if getattr(feature, "_metal_plate_lap_source", None) == _METAL_PLATE_LAP_TAG:
            return True
    except Exception:
        pass

    try:
        attributes = getattr(feature, "attributes", None) or {}
        if attributes.get("source") == _METAL_PLATE_LAP_TAG:
            return True
    except Exception:
        pass

    return False


def _clear_existing_metal_plate_laps(beams):
    cleared = 0
    seen = set()

    for beam in beams:
        beam_key = id(beam)
        if beam_key in seen:
            continue
        seen.add(beam_key)

        features = getattr(beam, "features", None)
        if not features:
            continue

        kept = []
        for feature in features:
            if _is_metal_plate_lap(feature):
                cleared += 1
            else:
                kept.append(feature)

        if len(kept) != len(features):
            beam.features = kept

    if cleared:
        print("  Cleared {} previous metal plate laps".format(cleared))

    return cleared


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
    arch_plate=(0.065, 0.146, 0.005),
    base_beam_height=0.14,
    base_plate=(0.065, 0.146, 0.005),
    arch_plate_width_offset=0.0075,
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
        is_base_base_joint = cat_a == "base" and cat_b == "base"

        # LLap joint: no metal plates on base beams.
        # LMiter joint (use_llap_joint=False): include base beam joints.
        # Non-base arch joints: always included regardless of toggle.
        # Skip mixed base/arch joints when toggle is LLap; base-base LMiter
        # joints still need their metal plate pockets.
        if is_base_joint and not is_base_base_joint and use_llap_joint:
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
        is_arch_joint = _is_arch_joint(beam_a, beam_b)
        if is_arch_joint:
            fallback_width = arch_beam_height
            plate_size = arch_plate
        else:
            fallback_width = base_beam_height
            plate_size = base_plate

        plate_thickness = plate_size[2]

        # Shared in-plane shift ("push the plate away from the face edge"). Both
        # beams' pockets move by the SAME vector so they stay coherent as a single
        # flat plate. Applying each beam's own zaxis (as before) diverges for
        # inclined arch beams whose zaxes differ by the joint angle, which warps
        # the pocket at larger offsets. We average the two beam height axes and
        # project the result into the shared face plane so the shift never changes
        # the pocket depth.
        if is_arch_joint and not is_base_joint:
            avg_z = Vector(*beam_a.frame.zaxis) + Vector(*beam_b.frame.zaxis)
            avg_z = avg_z - normal * avg_z.dot(normal)
            if avg_z.length:
                avg_z.unitize()
            width_shift = avg_z * (-arch_plate_width_offset)
        else:
            width_shift = Vector(0.0, 0.0, 0.0)

        def _lap_box(beam, side, is_arch_joint):
            if is_base_joint:
                # Use same world-Z direction as the visual plate so pockets land
                # on the top/bottom surfaces, not the side faces.
                desired_normal = normal
            else:
                # The visual plate follows the joint bisector, but BTLx Lap
                # parameters are more reliable when the final negative volume
                # snaps to the closest target beam reference side.
                desired_normal = _project_off_bisector(Vector(*beam.frame.yaxis))
                if desired_normal.length < 0.01:
                    desired_normal = normal

            local_normal, beam_size = _beam_side_axis(beam, desired_normal)
            if beam_size is None:
                beam_size = fallback_width

            lap_normal = local_normal * side
            lap_origin = joint_pt + lap_normal * (beam_size / 2 - plate_thickness / 2)
            lap_origin = lap_origin + width_shift

            lap_frame = _beam_local_lap_frame(beam, lap_origin, lap_normal, bisector)
            return Box(
                plate_size[1],
                plate_size[0],
                plate_size[2],
                frame=_rotate_frame_in_plane(lap_frame),
            )

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
            lap_box_a = _lap_box(beam_a, side, is_arch_joint)
            lap_box_b = _lap_box(beam_b, side, is_arch_joint)

            contact_normal = Vector(
                -normal.x * side, -normal.y * side, -normal.z * side
            )

            results.append(
                (visual_box, beam_a, beam_b, contact_normal, lap_box_a, lap_box_b)
            )

    return results


def _volume_centroid_xyz(brep):
    """Return the (x, y, z) centroid of a lap volume, with a vertex-average fallback."""

    try:
        c = brep.centroid
        return c.x, c.y, c.z
    except Exception:
        verts = [v.point for v in brep.vertices]
        count = len(verts) or 1
        return (
            sum(p.x for p in verts) / count,
            sum(p.y for p in verts) / count,
            sum(p.z for p in verts) / count,
        )


def _ref_side_index_for_volume(beam, brep):
    """Pick the longitudinal beam face the pocket sits against.

    The metal-plate pocket is a thin volume lying flush on one beam side face.
    The correct BTLx reference side is the longitudinal face (index 0-3; 4 and 5
    are the beam ends) whose outward normal points from the beam axis toward the
    volume centroid. Choosing it explicitly avoids compas_timber's default
    ``_get_optimal_ref_side_index`` heuristic, which counts edge/plane
    intersections and flips to the wrong face once the plate's in-plane size
    grows past a threshold (turning a shallow surface pocket into a deep slot
    that cuts through the beam).

    Reference-side normals are radial (perpendicular to the beam axis), so the
    axial component of ``centroid - axis_point`` cancels in every dot product;
    any point on the centerline works as the origin.
    """

    cx, cy, cz = _volume_centroid_xyz(brep)
    origin = beam.frame.point
    ox, oy, oz = cx - origin.x, cy - origin.y, cz - origin.z

    best_index = 0
    best_dot = None
    for index in range(4):
        normal = beam.ref_sides[index].normal
        dot = normal.x * ox + normal.y * oy + normal.z * oz
        if best_dot is None or dot > best_dot:
            best_dot = dot
            best_index = index

    return best_index


class _LapResult(object):
    """Holder exposing ``.volume`` so the existing GH viz code keeps working.

    ``Pocket`` returns a bare processing (no ``.volume``); the component reads
    ``lap.volume`` to emit ``metal_lap_volumes``. This wraps the processing
    together with its reconstructed machining volume.
    """

    def __init__(self, processing, volume):
        self.processing = processing
        self.volume = volume


def apply_laps(brep_beam_pairs, clear_existing=True):
    """
    Apply a Pocket feature to each (brep, beam) pair.

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

    pairs = list(brep_beam_pairs)

    if clear_existing:
        _clear_existing_metal_plate_laps([beam for _, beam in pairs])

    for brep, beam in pairs:
        try:
            ref_side_index = _ref_side_index_for_volume(beam, brep)
            pocket = Pocket.from_volume_and_element(
                brep, beam, ref_side_index=ref_side_index
            )
            _mark_metal_plate_lap(pocket)
            beam.add_feature(pocket)
            # Expose the input volume (a Brep) for the GH viz, matching how
            # LapProxy.volume behaved — the reconstructed Pocket volume is a
            # Polyhedron, which the viz path can't convert.
            lap_beam_pairs.append((_LapResult(pocket, brep), beam))
            print("  Pocket added")
        except Exception as e:
            print(f"  Warning pocket: {e}")

    return lap_beam_pairs
