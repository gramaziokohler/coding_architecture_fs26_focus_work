# r: compas==2.15.1,timber_design==0.2.0,compas_fab==1.1.4
# venv: ca-fs26-focus-work

from compas.data import json_dump


ghenv.Component.Message = "Export TimberModel"


TEMP_EXPORT_ATTRIBUTE_PREFIXES = ()

TEMP_EXPORT_ATTRIBUTE_KEYS = (
    "trimmed_geometry",
    "is_trimmed_inner_geometry",
)


def iter_model_beams(model):
    """Yield beams from a TimberModel across COMPAS Timber versions."""

    beams = getattr(model, "beams", None)
    if beams is not None:
        for beam in beams:
            yield beam
        return

    elements = getattr(model, "elements", None)
    if elements is not None:
        for element in elements:
            if hasattr(element, "attributes"):
                yield element


def iter_model_joints(model):
    """Yield joints/interactions from a TimberModel across COMPAS Timber versions."""

    joints = getattr(model, "joints", None)
    if joints is not None:
        for joint in joints:
            yield joint
        return

    interactions = getattr(model, "interactions", None)
    if interactions is not None:
        for interaction in interactions:
            yield interaction


def strip_temporary_export_attributes(model):
    """Remove temporary preview/helper attributes before JSON export.

    The custom joint classes are preserved. Only transient Grasshopper preview
    fields and cached construction helpers are stripped because they contain
    Rhino planes, COMPAS planes, or beam object references that are not part of
    the durable TimberModel description.
    """

    removed = []

    for beam in iter_model_beams(model):
        attributes = getattr(beam, "attributes", None)
        if not attributes:
            continue

        keys = []
        for key in list(attributes):
            if key in TEMP_EXPORT_ATTRIBUTE_KEYS:
                keys.append(key)
                continue
            if any(key.startswith(prefix) for prefix in TEMP_EXPORT_ATTRIBUTE_PREFIXES):
                keys.append(key)

        for key in keys:
            removed.append((beam, key, attributes.pop(key)))

    return removed


def restore_temporary_export_attributes(removed):
    for beam, key, value in removed:
        beam.attributes[key] = value


def mark_feature_as_standalone(feature):
    try:
        feature.is_joinery = False
    except Exception:
        try:
            feature.__dict__["is_joinery"] = False
        except Exception:
            pass

    try:
        feature.is_standalone_fabrication_feature = True
    except Exception:
        pass


def mark_standalone_inner_jack_rafter_cut_features(model):
    """Keep free-end JackRafterCuts in Beam.features during JSON export."""

    marked = 0

    for beam in iter_model_beams(model):
        attributes = getattr(beam, "attributes", None) or {}
        if not attributes.get("inner_jack_rafter_cut"):
            continue

        for feature in getattr(beam, "features", None) or []:
            if type(feature).__name__ != "JackRafterCut":
                continue

            mark_feature_as_standalone(feature)
            marked += 1

    return marked


def collect_joint_feature_ids(model):
    feature_ids = set()

    for joint in iter_model_joints(model):
        for feature in getattr(joint, "features", None) or []:
            feature_ids.add(id(feature))

    return feature_ids


def is_export_generated_joinery_feature(feature):
    feature_type = type(feature).__name__
    return feature_type == "LapProxy"


def strip_temporary_joinery_features(model):
    """Remove generated joint-owned features before JSON export.

    COMPAS Timber does not serialize joinery features on beams; it serializes
    the joints and recreates the features via ``process_joinery``. Some LapProxy
    features unproxy during the normal ``is_joinery`` check and can fail on
    edge-case machining parameters, so we remove those temporarily. Standalone
    fabrication features, such as extra JackRafterCuts for trimmed inner beams,
    stay on the beam and are serialized.
    """

    removed = []
    joint_feature_ids = collect_joint_feature_ids(model)

    for beam in iter_model_beams(model):
        features = getattr(beam, "features", None)
        if not features:
            continue

        kept = []
        for feature in features:
            if id(feature) in joint_feature_ids or is_export_generated_joinery_feature(feature):
                removed.append((beam, feature))
            else:
                kept.append(feature)

        if len(kept) != len(features):
            beam.features = kept

    return removed


def restore_temporary_joinery_features(removed):
    for beam, feature in removed:
        features = getattr(beam, "features", None)
        if features is None:
            beam.features = [feature]
        else:
            features.append(feature)


def iter_feature_values(feature):
    """Yield possible feature parameters without assuming a COMPAS version."""

    for name in ("inclination", "angle", "orientation", "start_x"):
        try:
            value = getattr(feature, name)
        except Exception:
            continue
        yield name, value

    data = getattr(feature, "__dict__", None)
    if isinstance(data, dict):
        for name, value in data.items():
            if name in ("inclination", "angle", "orientation", "start_x"):
                yield name, value


def collect_feature_export_issues(model):
    issues = []

    for beam_index, beam in enumerate(iter_model_beams(model)):
        beam_guid = str(getattr(beam, "guid", ""))
        beam_name = getattr(beam, "name", None)
        beam_label = beam_name or beam_guid or "beam[{}]".format(beam_index)
        features = getattr(beam, "features", None) or []

        for feature_index, feature in enumerate(features):
            feature_type = type(feature).__name__
            values = dict(iter_feature_values(feature))
            inclination = values.get("inclination")
            try:
                inclination_value = float(inclination)
            except Exception:
                inclination_value = None

            if inclination_value is not None and not (0.1 <= inclination_value <= 179.9):
                issues.append(
                    "{} feature[{}] {} has invalid inclination {}".format(
                        beam_label,
                        feature_index,
                        feature_type,
                        inclination_value,
                    )
                )

    return issues


export_message = "Check 'run' state and ensure 'path' is a complete file path."
removed_attributes_count = 0
removed_features_count = 0
marked_standalone_jack_rafter_count = 0

if run and path:
    if not path.lower().endswith(".json"):
        path += ".json"

    removed_attributes = strip_temporary_export_attributes(model)
    removed_attributes_count = len(removed_attributes)
    marked_standalone_jack_rafter_count = mark_standalone_inner_jack_rafter_cut_features(model)
    removed_features = strip_temporary_joinery_features(model)
    removed_features_count = len(removed_features)

    try:
        json_dump(model, path)
        export_message = "Model successfully saved to: {}".format(path)
    except Exception as error:
        print("Model export failed: {}".format(error))
        for issue in collect_feature_export_issues(model):
            print("Export issue: {}".format(issue))
        raise
    finally:
        restore_temporary_joinery_features(removed_features)
        restore_temporary_export_attributes(removed_attributes)
else:
    export_message = "Check 'run' state and ensure 'path' is a complete file path."

print(export_message)
if removed_attributes_count:
    print("Removed {} temporary preview geometry attributes for export only.".format(removed_attributes_count))
if removed_features_count:
    print("Removed {} generated joint-owned features for export only.".format(removed_features_count))
if marked_standalone_jack_rafter_count:
    print("Marked {} inner JackRafterCut features as standalone for export.".format(marked_standalone_jack_rafter_count))
