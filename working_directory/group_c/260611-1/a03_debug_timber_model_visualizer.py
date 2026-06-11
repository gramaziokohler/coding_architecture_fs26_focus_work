import Rhino.Geometry as rg

from compas.geometry import Point


def _short_guid(obj, length=8):
    return str(getattr(obj, "guid", ""))[:length]


def _to_rhino_point(point):
    if isinstance(point, Point):
        return rg.Point3d(point.x, point.y, point.z)
    if hasattr(point, "X") and hasattr(point, "Y") and hasattr(point, "Z"):
        return rg.Point3d(point.X, point.Y, point.Z)
    if hasattr(point, "x") and hasattr(point, "y") and hasattr(point, "z"):
        return rg.Point3d(point.x, point.y, point.z)
    return rg.Point3d(point[0], point[1], point[2])


def _rhino_line_from_compas(line):
    return rg.LineCurve(_to_rhino_point(line.start), _to_rhino_point(line.end))


def _beam_label(beam, index):
    category = beam.attributes.get("category")
    edge = beam.attributes.get("edge")
    parts = ["B{}".format(index), _short_guid(beam)]
    if category:
        parts.append(str(category))
    if edge is not None:
        parts.append("edge={}".format(edge))
    return " | ".join(parts)


def _interaction_label(interaction, index, prefix):
    interaction_type = type(interaction).__name__
    beam_ids = [_short_guid(beam) for beam in getattr(interaction, "elements", [])]
    return "{}{} {} ({})".format(prefix, index, interaction_type, ", ".join(beam_ids))


def _interaction_location(interaction):
    return _to_rhino_point(interaction.location)


def _make_dot(text, point):
    dot = rg.TextDot(text, point)
    dot.FontHeight = 10
    return dot


def create_timber_model_debug_geometry(model, show_candidates=True):
    """Create Rhino/GH debug geometry for a TimberModel.

    Returns a dictionary with:
    - beam_centerlines
    - beam_tags
    - joint_points
    - joint_tags
    - joint_links
    - candidate_points
    - candidate_tags
    - candidate_links

    Text tags are Rhino.Geometry.TextDot objects and can be output directly from
    a Grasshopper Python component.
    """
    beam_centerlines = []
    beam_tags = []
    joint_points = []
    joint_tags = []
    joint_links = []
    candidate_points = []
    candidate_tags = []
    candidate_links = []

    beams = list(model.beams)
    beam_index_by_guid = {str(beam.guid): i for i, beam in enumerate(beams)}

    for index, beam in enumerate(beams):
        beam_centerlines.append(_rhino_line_from_compas(beam.centerline))
        beam_tags.append(_make_dot(_beam_label(beam, index), _to_rhino_point(beam.centerline.midpoint)))

    joints = list(model.joints)
    for index, joint in enumerate(joints):
        location = _interaction_location(joint)
        label = _interaction_label(joint, index, "J")

        joint_points.append(location)
        joint_tags.append(_make_dot(label, location))

        print("{} at {}".format(label, location))
        for beam in getattr(joint, "elements", []):
            beam_index = beam_index_by_guid.get(str(beam.guid), "?")
            joint_links.append(rg.LineCurve(location, _to_rhino_point(beam.centerline.midpoint)))
            print("  beam B{} {} category={}".format(
                beam_index,
                _short_guid(beam),
                beam.attributes.get("category"),
            ))

    if show_candidates:
        candidates = list(model.joint_candidates)
        for index, candidate in enumerate(candidates):
            location = _interaction_location(candidate)
            label = _interaction_label(candidate, index, "C")

            candidate_points.append(location)
            candidate_tags.append(_make_dot(label, location))

            print("{} at {}".format(label, location))
            for beam in getattr(candidate, "elements", []):
                beam_index = beam_index_by_guid.get(str(beam.guid), "?")
                candidate_links.append(rg.LineCurve(location, _to_rhino_point(beam.centerline.midpoint)))
                print("  beam B{} {} category={}".format(
                    beam_index,
                    _short_guid(beam),
                    beam.attributes.get("category"),
                ))

    print("Beams: {}".format(len(beams)))
    print("Joints: {}".format(len(joints)))
    print("Candidates: {}".format(len(list(model.joint_candidates))))

    return {
        "beam_centerlines": beam_centerlines,
        "beam_tags": beam_tags,
        "joint_points": joint_points,
        "joint_tags": joint_tags,
        "joint_links": joint_links,
        "candidate_points": candidate_points,
        "candidate_tags": candidate_tags,
        "candidate_links": candidate_links,
    }
