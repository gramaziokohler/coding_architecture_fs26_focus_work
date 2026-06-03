from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import closest_point_on_segment
from compas.geometry import distance_point_line
from compas.geometry import distance_point_point
from compas.itertools import pairwise
from compas_timber.connections import JointCandidate
from compas_timber.connections import JointTopology
from compas_timber.elements import Beam


def _to_compas_point(point):
    if isinstance(point, Point):
        return point
    if hasattr(point, "X") and hasattr(point, "Y") and hasattr(point, "Z"):
        return Point(point.X, point.Y, point.Z)
    if hasattr(point, "x") and hasattr(point, "y") and hasattr(point, "z"):
        return Point(point.x, point.y, point.z)
    return Point(*point)


def _copy_beam_attributes(source, target):
    target.attributes.update(source.attributes)
    target.attributes["parent_beam_guid"] = str(source.guid)


def _point_data(point):
    return [point.x, point.y, point.z]


def _add_support_marker(beam, point, end_key):
    support_points = list(beam.attributes.get("support_points", []))
    point_data = _point_data(point)
    if point_data not in support_points:
        support_points.append(point_data)

    beam.attributes["is_support_split"] = True
    beam.attributes["support_points"] = support_points
    beam.attributes[end_key] = True


def _deduplicate_points_on_line(points_with_distances, tolerance):
    deduplicated = []
    for distance, point in sorted(points_with_distances, key=lambda item: item[0]):
        if deduplicated and abs(distance - deduplicated[-1][0]) <= tolerance:
            continue
        deduplicated.append((distance, point))
    return deduplicated


def split_beams_at_points_with_i_joints(model, split_points, tolerance=0.01, remove_old_interactions=True, mark_supports=True):
    """Physically split beams and add no-op I-topology joints between split pieces.

    Parameters
    ----------
    model
        TimberModel to modify in place.
    split_points
        Rhino Point3d, COMPAS Point, or xyz tuples.
    tolerance
        Max distance for a split point to be considered on a beam centerline.
    remove_old_interactions
        If True, remove joints/candidates involving beams that are replaced.
        This avoids stale graph references, but external joints must be rebuilt
        afterwards by your normal joint/topology workflow.
    mark_supports
        If True, the split locations are stored on adjacent new beams as
        support_points plus support_start/support_end flags.
    """
    compas_points = [_to_compas_point(point) for point in split_points or []]

    replacements = []

    for beam in list(model.beams):
        centerline = beam.centerline
        split_points_with_distances = []

        for point in compas_points:
            if distance_point_line(point, (centerline.start, centerline.end)) > tolerance:
                continue

            projected = Point(*closest_point_on_segment(point, centerline))
            distance_from_start = distance_point_point(centerline.start, projected)
            distance_from_end = beam.length - distance_from_start

            if distance_from_start <= tolerance or distance_from_end <= tolerance:
                continue

            split_points_with_distances.append((distance_from_start, projected))

        split_points_with_distances = _deduplicate_points_on_line(split_points_with_distances, tolerance)
        if not split_points_with_distances:
            continue

        ordered_points = [item[1] for item in split_points_with_distances]
        segment_points = [centerline.start] + ordered_points + [centerline.end]

        new_beams = []
        for start, end in pairwise(segment_points):
            if distance_point_point(start, end) <= tolerance:
                continue

            new_beam = Beam.from_centerline(
                centerline=Line(start, end),
                width=beam.width,
                height=beam.height,
                z_vector=beam.frame.zaxis,
            )
            _copy_beam_attributes(beam, new_beam)
            new_beams.append(new_beam)

        replacements.append((beam, new_beams, ordered_points))

    for old_beam, _, _ in replacements:
        if remove_old_interactions:
            for joint in list(model.get_joints_for_element(old_beam)):
                model.remove_joint(joint)
            for candidate in list(model.get_candidates_for_element(old_beam)):
                model.remove_joint_candidate(candidate)

        model.remove_element(old_beam)

    for _, new_beams, split_locations in replacements:
        for new_beam in new_beams:
            model.add_element(new_beam)

        for beam_a, beam_b, location in zip(new_beams[:-1], new_beams[1:], split_locations):
            if mark_supports:
                _add_support_marker(beam_a, location, "support_end")
                _add_support_marker(beam_b, location, "support_start")

            i_joint = JointCandidate(
                beam_a,
                beam_b,
                topology=JointTopology.TOPO_I,
                location=location,
                distance=0.0,
            )
            model.add_joint(i_joint)

    return model
