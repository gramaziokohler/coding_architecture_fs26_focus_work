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


def _is_same_beam(a, b):
    if a is b:
        return True
    return getattr(a, "guid", None) == getattr(b, "guid", None)


def _beam_category(beam):
    return getattr(beam, "attributes", {}).get("category")


def _terminal_main_joints_for_beam(model, beam, joint_type_names, end_region):
    joints = []
    for joint in model.get_joints_for_element(beam):
        if _joint_type_name(joint) not in joint_type_names:
            continue
        if not _is_same_beam(getattr(joint, "main_beam", None), beam):
            continue

        location = _joint_location(joint)
        distance = _distance_along_beam(beam, location)
        distance_from_start = distance
        distance_from_end = beam.length - distance
        end_distance = min(distance_from_start, distance_from_end)

        if end_region is not None and end_distance > end_region:
            continue

        end_key = "start" if distance_from_start <= distance_from_end else "end"
        joints.append({
            "distance": distance,
            "distance_from_start": distance_from_start,
            "distance_from_end": distance_from_end,
            "end_distance": end_distance,
            "end": end_key,
            "joint": joint,
            "main_beam": beam,
            "cross_beam": getattr(joint, "cross_beam", None),
        })

    joints.sort(key=lambda item: item["distance"])
    return joints


def _tbutt_main_joints_for_beam(model, beam, end_region):
    return _terminal_main_joints_for_beam(model, beam, {"TButtJoint"}, end_region)


def _cluster_sorted_joints(joints_with_distances, cluster_distance):
    clusters = []
    current = []

    for item in joints_with_distances:
        if not current:
            current = [item]
            continue

        if item["distance"] - current[-1]["distance"] <= cluster_distance:
            current.append(item)
        else:
            clusters.append(current)
            current = [item]

    if current:
        clusters.append(current)

    return clusters


def _group_by_end(joints):
    groups = {"start": [], "end": []}
    for item in joints:
        groups[item["end"]].append(item)
    return groups


def _outer_items_in_cluster(cluster):
    end_key = cluster[0]["end"]

    if end_key == "start":
        # Closest to the physical beam start is outside the real trimmed end.
        keep = max(cluster, key=lambda item: item["distance_from_start"])
    else:
        # Closest to the physical beam end is outside the real trimmed end.
        keep = max(cluster, key=lambda item: item["distance_from_end"])

    return [item for item in cluster if item is not keep]


def _joint_keep_priority(item):
    joint_type = _joint_type_name(item["joint"])
    if joint_type == "TButtJoint":
        return 2
    if joint_type == "TBirdsmouthJoint":
        return 1
    return 0


def _inner_terminal_item_in_cluster(cluster):
    end_key = cluster[0]["end"]

    if end_key == "start":
        return max(
            cluster,
            key=lambda item: (item["distance_from_start"], _joint_keep_priority(item)),
        )

    return max(
        cluster,
        key=lambda item: (item["distance_from_end"], _joint_keep_priority(item)),
    )


def _outer_terminal_items_in_cluster(cluster):
    keep = _inner_terminal_item_in_cluster(cluster)
    return [item for item in cluster if item is not keep]


def find_outer_duplicate_tbutt_joints(model, cluster_distance=0.25, end_region=0.35):
    """Find likely duplicate TButt joints caused by tolerance-based detection.

    The test is role-aware: a beam can legitimately have many TButt joints as
    ``cross_beam``. A duplicate is only suspected when the same beam is the
    ``main_beam`` (the butting/trimmed beam) multiple times near the same end.
    In each duplicate cluster, the outer joint closest to the physical beam end
    is marked for removal.
    """
    removals = {}

    for beam in model.beams:
        joints = _tbutt_main_joints_for_beam(model, beam, end_region)
        if len(joints) < 2:
            continue

        for end_key, end_joints in _group_by_end(joints).items():
            if len(end_joints) < 2:
                continue

            for cluster in _cluster_sorted_joints(end_joints, cluster_distance):
                if len(cluster) < 2:
                    continue

                for item_to_remove in _outer_items_in_cluster(cluster):
                    joint_to_remove = item_to_remove["joint"]
                    removals[str(joint_to_remove.guid)] = {
                        "joint": joint_to_remove,
                        "beam": beam,
                        "end": end_key,
                        "cluster": cluster,
                        "item": item_to_remove,
                    }

    return list(removals.values())


def find_invalid_terminal_t_joints(
    model,
    cluster_distance=0.25,
    end_region=0.35,
    joint_type_names=None,
):
    """Find invalid terminal T-joint sequences on the same main beam end.

    This is a more general version of the TButt duplicate cleanup. It handles
    cases such as a ``TButtJoint`` followed by a ``TBirdsmouthJoint`` on the
    same physical end of the same main beam. Since these joints trim the
    ``main_beam`` at its end, there cannot be another terminal T-joint outside
    the inner trim position.
    """
    if joint_type_names is None:
        joint_type_names = {"TButtJoint", "TBirdsmouthJoint"}
    else:
        joint_type_names = set(joint_type_names)

    removals = {}

    for beam in model.beams:
        joints = _terminal_main_joints_for_beam(model, beam, joint_type_names, end_region)
        if len(joints) < 2:
            continue

        for end_key, end_joints in _group_by_end(joints).items():
            if len(end_joints) < 2:
                continue

            for cluster in _cluster_sorted_joints(end_joints, cluster_distance):
                if len(cluster) < 2:
                    continue

                for item_to_remove in _outer_terminal_items_in_cluster(cluster):
                    joint_to_remove = item_to_remove["joint"]
                    removals[str(joint_to_remove.guid)] = {
                        "joint": joint_to_remove,
                        "beam": beam,
                        "end": end_key,
                        "cluster": cluster,
                        "item": item_to_remove,
                    }

    return list(removals.values())


def remove_outer_duplicate_tbutt_joints(model, cluster_distance=0.25, end_region=0.35, dry_run=True):
    """Remove likely duplicate outer TButt joints from a TimberModel.

    Parameters
    ----------
    model
        TimberModel to clean.
    cluster_distance
        Maximum distance in model units between adjacent TButt joint locations
        along the same beam for them to be considered duplicates.
    end_region
        Only TButt joints within this distance from a main beam end are
        considered. Set to None to disable this additional safety check.
    dry_run
        If True, only print what would be removed.
    """
    removals = find_outer_duplicate_tbutt_joints(model, cluster_distance, end_region)

    for item in removals:
        joint = item["joint"]
        beam = item["beam"]
        cluster = item["cluster"]
        cross_beam = getattr(joint, "cross_beam", None)

        print("REMOVE {} {} main={} main_category={} end={} cross={} cross_category={}".format(
            _joint_type_name(joint),
            _short_guid(joint),
            _short_guid(beam),
            _beam_category(beam),
            item["end"],
            _short_guid(cross_beam),
            _beam_category(cross_beam),
        ))
        print("  cluster distances: {}".format(
            [round(entry["distance"], 4) for entry in cluster]
        ))
        print("  cluster end distances: {}".format(
            [round(entry["end_distance"], 4) for entry in cluster]
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


def remove_invalid_terminal_t_joints(
    model,
    cluster_distance=0.25,
    end_region=0.35,
    joint_type_names=None,
    dry_run=True,
):
    """Remove invalid terminal T-joint sequences from a TimberModel.

    The role rule is the same for every beam: only joints where the beam is
    ``main_beam`` are considered. Multiple joints where the beam is
    ``cross_beam`` are ignored because those are legitimate receiving-beam
    cases. In a duplicate terminal cluster, the inner joint is kept and the
    outer joints are removed. If two joints are at the same location,
    ``TButtJoint`` is preferred over ``TBirdsmouthJoint``.
    """
    removals = find_invalid_terminal_t_joints(
        model,
        cluster_distance=cluster_distance,
        end_region=end_region,
        joint_type_names=joint_type_names,
    )

    for item in removals:
        joint = item["joint"]
        beam = item["beam"]
        cluster = item["cluster"]
        cross_beam = getattr(joint, "cross_beam", None)

        print("REMOVE {} {} main={} main_category={} end={} cross={} cross_category={}".format(
            _joint_type_name(joint),
            _short_guid(joint),
            _short_guid(beam),
            _beam_category(beam),
            item["end"],
            _short_guid(cross_beam),
            _beam_category(cross_beam),
        ))
        print("  cluster types: {}".format(
            [_joint_type_name(entry["joint"]) for entry in cluster]
        ))
        print("  cluster distances: {}".format(
            [round(entry["distance"], 4) for entry in cluster]
        ))
        print("  cluster end distances: {}".format(
            [round(entry["end_distance"], 4) for entry in cluster]
        ))
        print("  connected beams: {}".format(
            [_short_guid(element) for element in joint.elements]
        ))

    if not dry_run:
        for item in removals:
            model.remove_joint(item["joint"])

    print("{} invalid terminal T joints {}".format(
        len(removals),
        "found" if dry_run else "removed",
    ))

    return model, removals
