# r: compas==2.15.1,timber_design==0.2.0,compas_fab==1.1.4
# venv: ca-fs26-focus-work

import json

from compas.data import json_dump


ghenv.Component.Message = "Export TimberModel"


CUSTOM_TBUTT_DTYPE = "a03_preferred_face_tbutt_joint/PreferredFaceTButtJoint"
STANDARD_TBUTT_DTYPE = "compas_timber.connections/TButtJoint"
CUSTOM_TBUTT_DATA_KEYS = (
    "preferred_face_vector",
    "forced_cross_beam_ref_side_index",
)


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
converted_tbutt_count = 0

if run and path:
    if not path.lower().endswith(".json"):
        path += ".json"

    json_dump(model, path)
    converted_tbutt_count = sanitize_export_json(path)
    export_message = "Model successfully saved to: {}".format(path)
else:
    export_message = "Check 'run' state and ensure 'path' is a complete file path."

print(export_message)
if converted_tbutt_count:
    print("Converted {} PreferredFaceTButtJoint records to standard TButtJoint for export.".format(converted_tbutt_count))
