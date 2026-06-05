# r: compas==2.15.1,timber_design==0.2.0,compas_fab==1.1.4
# venv: ca-fs26-focus-work

import json

from compas.data import json_dump


ghenv.Component.Message = "Export TimberModel"


TEMP_EXPORT_ATTRIBUTE_PREFIXES = (
    "inner_cutting_",
)

CUSTOM_TBUTT_DTYPE = "a03_preferred_face_tbutt_joint/PreferredFaceTButtJoint"
STANDARD_TBUTT_DTYPE = "compas_timber.connections/TButtJoint"
CUSTOM_TBUTT_DATA_KEYS = (
    "preferred_face_vector",
    "forced_cross_beam_ref_side_index",
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


def strip_temporary_export_attributes(model):
    """Remove temporary preview/helper attributes before JSON export.

    The trimmed-inner-beam workflow stores Rhino planes, COMPAS planes, and beam
    object references under ``inner_cutting_*`` keys. Those are useful while
    constructing and previewing the model, but they are not needed in the saved
    TimberModel and can break COMPAS JSON serialization.
    """

    removed = []

    for beam in iter_model_beams(model):
        attributes = getattr(beam, "attributes", None)
        if not attributes:
            continue

        keys = [
            key for key in list(attributes)
            if any(key.startswith(prefix) for prefix in TEMP_EXPORT_ATTRIBUTE_PREFIXES)
        ]

        for key in keys:
            removed.append((beam, key, attributes.pop(key)))

    return removed


def restore_temporary_export_attributes(removed):
    for beam, key, value in removed:
        beam.attributes[key] = value


def convert_custom_tbutt_joints_to_standard(data):
    """Rewrite exported PreferredFaceTButtJoint records as regular TButtJoint."""

    converted = 0

    if isinstance(data, dict):
        if data.get("dtype") == CUSTOM_TBUTT_DTYPE:
            data["dtype"] = STANDARD_TBUTT_DTYPE
            joint_data = data.get("data") or {}
            joint_data["name"] = "TButtJoint"
            for key in CUSTOM_TBUTT_DATA_KEYS:
                joint_data.pop(key, None)
            converted += 1

        for value in data.values():
            converted += convert_custom_tbutt_joints_to_standard(value)

    elif isinstance(data, list):
        for item in data:
            converted += convert_custom_tbutt_joints_to_standard(item)

    return converted


def sanitize_export_json(path):
    with open(path, "r") as fp:
        data = json.load(fp)

    converted_tbutt_count = convert_custom_tbutt_joints_to_standard(data)

    if converted_tbutt_count:
        with open(path, "w") as fp:
            json.dump(data, fp)

    return converted_tbutt_count


export_message = "Check 'run' state and ensure 'path' is a complete file path."
removed_attributes_count = 0
converted_tbutt_count = 0

if run and path:
    if not path.lower().endswith(".json"):
        path += ".json"

    removed_attributes = strip_temporary_export_attributes(model)
    removed_attributes_count = len(removed_attributes)

    try:
        json_dump(model, path)
        converted_tbutt_count = sanitize_export_json(path)
        export_message = "Model successfully saved to: {}".format(path)
    finally:
        restore_temporary_export_attributes(removed_attributes)
else:
    export_message = "Check 'run' state and ensure 'path' is a complete file path."

print(export_message)
if removed_attributes_count:
    print("Removed {} temporary inner_cutting_* attributes for export only.".format(removed_attributes_count))
if converted_tbutt_count:
    print("Converted {} PreferredFaceTButtJoint records to standard TButtJoint for export.".format(converted_tbutt_count))
