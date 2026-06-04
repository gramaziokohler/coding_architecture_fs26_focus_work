from compas.geometry import Point
from compas.geometry import closest_point_on_segment
from compas.geometry import distance_point_point


def _joint_type_name(joint):
    return type(joint).__name__


def _short_guid(obj, length=8):
    return str(getattr(obj, "guid", ""))[:length]


def _joint_location(joint):
    location = joint.location
    if isinstance(location, Point):
        return location
    return Point(*location)


def _distance_along_beam(beam, point):
    projected = Point(*closest_point_on_segment(point, beam.centerline))
    return distance_point_point(beam.centerline.start, projected)


def _tbutt_joints_for_beam(model, beam):
    joints = []
    for joint in model.get_joints_for_element(beam):
        if _joint_type_name(joint) != "TButtJoint":
            continue

        location = _joint_location(joint)
        distance = _distance_along_beam(beam, location)
        joints.append((distance, joint))

    joints.sort(key=lambda item: item[0])
    return joints


def _cluster_sorted_joints(joints_with_distances, cluster_distance):
    clusters = []
    current = []

    for item in joints_with_distances:
        if not current:
            current = [item]
            continue

        if item[0] - current[-1][0] <= cluster_distance:
            current.append(item)
        else:
            clusters.append(current)
            current = [item]

    if current:
        clusters.append(current)

    return clusters


def _outer_joint_in_cluster(beam, cluster):
    length = beam.length
    cluster_mid = sum(distance for distance, _ in cluster) / float(len(cluster))

    if cluster_mid <= length * 0.5:
        # Cluster is closer to beam start. The outer joint is the one closest to start.
        return min(cluster, key=lambda item: item[0])

    # Cluster is closer to beam end. The outer joint is the one closest to end.
    return max(cluster, key=lambda item: item[0])


def find_outer_duplicate_tbutt_joints(model, cluster_distance=0.25):
    """Find likely duplicate TButt joints caused by tolerance-based detection.

    For each beam, TButt joints are sorted along its centerline. Adjacent TButt
    joints within ``cluster_distance`` are treated as one duplicate cluster. In
    each cluster, the joint closest to the beam end is marked for removal.
    """
    removals = {}

    for beam in model.beams:
        joints = _tbutt_joints_for_beam(model, beam)
        if len(joints) < 2:
            continue

        for cluster in _cluster_sorted_joints(joints, cluster_distance):
            if len(cluster) < 2:
                continue

            _, joint_to_remove = _outer_joint_in_cluster(beam, cluster)
            removals[str(joint_to_remove.guid)] = {
                "joint": joint_to_remove,
                "beam": beam,
                "cluster": cluster,
            }

    return list(removals.values())


def remove_outer_duplicate_tbutt_joints(model, cluster_distance=0.25, dry_run=True):
    """Remove likely duplicate outer TButt joints from a TimberModel.

    Parameters
    ----------
    model
        TimberModel to clean.
    cluster_distance
        Maximum distance in model units between adjacent TButt joint locations
        along the same beam for them to be considered duplicates.
    dry_run
        If True, only print what would be removed.
    """
    removals = find_outer_duplicate_tbutt_joints(model, cluster_distance)

    for item in removals:
        joint = item["joint"]
        beam = item["beam"]
        cluster = item["cluster"]

        print("REMOVE {} {} on beam {} category={}".format(
            _joint_type_name(joint),
            _short_guid(joint),
            _short_guid(beam),
            beam.attributes.get("category"),
        ))
        print("  cluster distances: {}".format(
            [round(distance, 4) for distance, _ in cluster]
        ))
        print("  connected beams: {}".format(
            [_short_guid(element) for element in joint.elements]
        ))

    if not dry_run:
        for item in removals:
            model.remove_joint(item["joint"])

    print("{} duplicate TButt joints {}".format(
        len(removals),
        "found" if dry_run else "removed",
    ))

    return model, removals
