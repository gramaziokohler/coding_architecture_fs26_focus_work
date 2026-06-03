from compas_rhino.devtools import DevTools

DevTools.ensure_path()
ghenv.Component.Message = "Metal Plates"

import Rhino.Geometry as rg
from compas.geometry import Box, Frame, Vector, Point, cross_vectors, Plane
from compas_rhino.conversions import box_to_rhino
from compas_timber.connections import LMiterJoint

beam_height = vars().get("beam_height") or 0.10

plates = []

if timber_model:
    joints = timber_model.joints

    for joint in joints:
        if not isinstance(joint, LMiterJoint):
            continue

        beam_a = joint.beam_a
        beam_b = joint.beam_b
        if beam_a is None or beam_b is None:
            continue

        joint_pt = joint.location

        # direction vectors along each beam, flipped to point away from the corner
        vA = Vector(*beam_a.frame.xaxis)
        vB = Vector(*beam_b.frame.xaxis)
        tA, _ = beam_a.endpoint_closest_to_point(joint_pt)
        if tA == "end":
            vA *= -1.0
        tB, _ = beam_b.endpoint_closest_to_point(joint_pt)
        if tB == "end":
            vB *= -1.0

        # x-axis: bisector of the two beams (long axis of the plate, 180 mm)
        x_axis = vA + vB
        x_axis.unitize()

        # z-axis: beam height normal – the z_vector used when creating the beam
        z_axis = Vector(*beam_a.frame.yaxis)
        z_axis.unitize()

        # y-axis: perpendicular to bisector in the top-surface plane (40 mm)
        y_axis = Vector(*cross_vectors(z_axis, x_axis))
        y_axis.unitize()

        # shift the joint point to the top surface
        offset_pt_top = Point(
            joint_pt.x + z_axis.x * (beam_height / 2),
            joint_pt.y + z_axis.y * (beam_height / 2),
            joint_pt.z + z_axis.z * (beam_height / 2),
        )

        bisector = beam_a.centerline.direction + beam_b.centerline.direction
        bisector.unitize()

        for side in [1, -1]:
            plate_frame = Frame.from_plane(Plane(joint.location, beam_a.frame.yaxis))
            plate_frame.translate(beam_a.frame.yaxis * side * beam_height / 2)

            plate_frame.xaxis = plate_frame.zaxis.cross(bisector)
            plate_frame.yaxis = bisector

            compas_box = Box(0.040, 0.180, 0.0025, frame=plate_frame)

            try:
                rhino_box = box_to_rhino(compas_box)
                brep = rg.Brep.CreateFromBox(rhino_box)
                if brep:
                    plates.append(brep)
            except Exception as e:
                print(f"Warning: could not convert plate to Brep: {e}")

count = len(plates)
print(plates)
print(f"Created {count} metal plates")
