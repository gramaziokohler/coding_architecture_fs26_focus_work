"""
Stencil helpers for plates with circular openings and 60x80 timber beams.
"""

import math

from compas.geometry import Frame
from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.scene import SceneObject
from compas_timber.connections import JointTopology
from compas_timber.connections import LLapJoint
from compas_timber.connections import TLapJoint
from compas_timber.connections import XLapJoint
from compas_timber.elements import Beam
from compas_timber.elements import Plate
from compas_timber.model import TimberModel
from timber_design.workflow import JointRuleSolver
from timber_design.workflow import TopologyRule


def point_to_compas(point):
    return Point(point.X, point.Y, point.Z)


def vector_to_compas(vector):
    return Vector(vector.X, vector.Y, vector.Z)


def line_to_compas(line):
    return Line(point_to_compas(line.From), point_to_compas(line.To))


def rectangle_frame(rectangle):
    plane = rectangle.Plane
    return Frame(
        point_to_compas(plane.Origin),
        vector_to_compas(plane.XAxis),
        vector_to_compas(plane.YAxis),
    )


def rectangle_outline(rectangle):
    corners = [point_to_compas(rectangle.Corner(i)) for i in range(4)]
    corners.append(corners[0])
    return Polyline(corners)


def point_in_rectangle(rectangle, point):
    return rectangle.Contains(point) != 0


def circle_polyline(frame, center, radius, segments):
    points = []
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        points.append(
            center
            + frame.xaxis * (math.cos(angle) * radius)
            + frame.yaxis * (math.sin(angle) * radius)
        )
    points.append(points[0])
    return Polyline(points)


def hole_openings(rectangle, points, hole_radius=0.015, hole_segments=24):
    frame = rectangle_frame(rectangle)
    openings = []

    for point in points or []:
        if not point_in_rectangle(rectangle, point):
            continue

        center = point_to_compas(point)
        openings.append(circle_polyline(frame, center, hole_radius, hole_segments))

    return openings


def make_plate(rectangle, points, plate_thickness=0.010, hole_radius=0.015, hole_segments=24):
    return Plate.from_outline_thickness(
        rectangle_outline(rectangle),
        plate_thickness,
        vector=rectangle_frame(rectangle).zaxis,
        openings=hole_openings(rectangle, points, hole_radius, hole_segments),
    )


def make_beam(line, beam_width=0.060, beam_height=0.080):
    return Beam.from_centerline(
        line_to_compas(line),
        width=beam_width,
        height=beam_height,
        z_vector=Vector(0, 0, 1),
    )


def add_lap_joints(model, joint_max_distance=0.020, lap_cut_plane_bias=0.5, flip_lap_side=False, include_x_lap=True):
    rules = [
        TopologyRule(
            JointTopology.TOPO_T,
            TLapJoint,
            max_distance=joint_max_distance,
            cut_plane_bias=lap_cut_plane_bias,
            flip_lap_side=flip_lap_side,
        ),
        TopologyRule(
            JointTopology.TOPO_L,
            LLapJoint,
            max_distance=joint_max_distance,
            cut_plane_bias=lap_cut_plane_bias,
            flip_lap_side=flip_lap_side,
        )
    ]
    if include_x_lap:
        rules.append(
            TopologyRule(
                JointTopology.TOPO_X,
                XLapJoint,
                max_distance=joint_max_distance,
                cut_plane_bias=lap_cut_plane_bias,
                flip_lap_side=flip_lap_side,
            )
        )
    solver = JointRuleSolver(rules)
    return solver.apply_rules_to_model(model)


def element_geometry(element, errors, compute_plate_geometry=True):
    if isinstance(element, Plate) and not compute_plate_geometry:
        try:
            return element.blank.to_mesh()
        except Exception as error:
            errors.append("Plate blank preview: {!r}".format(error))

    try:
        return element.geometry
    except Exception as error:
        errors.append("{} geometry: {!r}".format(type(element).__name__, error))
        if isinstance(element, Plate):
            try:
                geometry = element.compute_elementgeometry(include_features=False)
                return geometry.transformed(element.modeltransformation)
            except Exception as fallback_error:
                errors.append("Plate shape fallback: {!r}".format(fallback_error))
            try:
                return element.blank.to_mesh()
            except Exception as blank_error:
                errors.append("Plate blank fallback: {!r}".format(blank_error))
        return None


def rhino_geometry(geometry, errors):
    if geometry is None:
        return None

    try:
        return SceneObject(item=geometry).draw()
    except Exception as error:
        errors.append("Rhino conversion: {}".format(error))
        return None


def make_geometry_outputs(plates, beams, compute_plate_geometry=True):
    geometry_errors = []
    plates_out = [element_geometry(plate, geometry_errors, compute_plate_geometry) for plate in plates]
    beams_out = [element_geometry(beam, geometry_errors) for beam in beams]

    plate_holes_out = []
    for plate in plates:
        for opening in plate.plate_geometry.openings:
            plate_holes_out.append(opening.transformed(plate.modeltransformation))

    plate_holes_rhino = [rhino_geometry(hole, geometry_errors) for hole in plate_holes_out]
    plates_rhino = [rhino_geometry(geometry, geometry_errors) for geometry in plates_out]
    beams_rhino = [rhino_geometry(geometry, geometry_errors) for geometry in beams_out]

    return plates_out, beams_out, plate_holes_out, plate_holes_rhino, plates_rhino, beams_rhino, geometry_errors


def create_stencil(
    rectangles,
    points,
    frame_beam_lines=None,  # Neu aufgeteilt
    plate_beam_lines=None,  # Neu aufgeteilt
    plate_thickness=0.010,
    hole_radius=0.015,
    hole_segments=24,
    frame_beam_width=0.060,   # Separat für Rahmen
    frame_beam_height=0.080,  # Separat für Rahmen
    plate_beam_width=0.090,   # Separat für Plattenbalken (Beispielwert)
    plate_beam_height=0.090,  # Separat für Plattenbalken (Beispielwert)
    joint_max_distance=0.020,
    tbutt_mill_depth=0.001,
    lap_cut_plane_bias=0.5,
    flip_lap_side=False,
    include_x_lap=True,
    process_joinery=False,
    compute_plate_geometry=False,
):
    """Create plates, beams, lap joints, and preview geometry with mixed beam sizes."""

    rectangles = rectangles or []
    points = points or []
    frame_beam_lines = frame_beam_lines or []
    plate_beam_lines = plate_beam_lines or []

    # 1. Platten erstellen
    plates = [
        make_plate(
            rectangle,
            points,
            plate_thickness=plate_thickness,
            hole_radius=hole_radius,
            hole_segments=hole_segments,
        )
        for rectangle in rectangles
    ]
    
    # 2. Balken getrennt mit ihren jeweiligen Dimensionen erstellen
    frame_beams = [
        make_beam(line, beam_width=frame_beam_width, beam_height=frame_beam_height) 
        for line in frame_beam_lines
    ]
    plate_beams = [
        make_beam(line, beam_width=plate_beam_width, beam_height=plate_beam_height) 
        for line in plate_beam_lines
    ]

    # Alle Balken für das TimberModel zusammenführen
    beams = frame_beams + plate_beams

    # 3. Timber Model befüllen
    timber_model = TimberModel()
    for plate in plates:
        timber_model.add_element(plate)
    for beam in beams:
        timber_model.add_element(beam)

    # Verbindungen berechnen (Verbindet frame_beams und plate_beams automatisch, falls sie sich schneiden)
    joining_errors, unjoined_clusters = add_lap_joints(
        timber_model,
        joint_max_distance=joint_max_distance,
        lap_cut_plane_bias=lap_cut_plane_bias,
        flip_lap_side=flip_lap_side,
        include_x_lap=include_x_lap,
    )

    if process_joinery:
        timber_model.process_joinery()

    # 4. Geometrie-Ausgabe generieren
    # Da make_geometry_outputs Listen verarbeitet, können wir die Geometrien getrennt jagen
    geometry_errors = []
    plates_out = [element_geometry(plate, geometry_errors, compute_plate_geometry) for plate in plates]
    
    # Ausgaben für Rhino getrennt berechnen
    frame_beams_out = [element_geometry(beam, geometry_errors) for beam in frame_beams]
    plate_beams_out = [element_geometry(beam, geometry_errors) for beam in plate_beams]
    
    frame_beams_rhino = [rhino_geometry(geom, geometry_errors) for geom in frame_beams_out]
    plate_beams_rhino = [rhino_geometry(geom, geometry_errors) for geom in plate_beams_out]

    # Löcher und Platten-Rhino-Geometrie
    plate_holes_out = []
    for plate in plates:
        for opening in plate.plate_geometry.openings:
            plate_holes_out.append(opening.transformed(plate.modeltransformation))

    plate_holes_rhino = [rhino_geometry(hole, geometry_errors) for hole in plate_holes_out]
    plates_rhino = [rhino_geometry(geometry, geometry_errors) for geometry in plates_out]

    # Gelenke auswerten
    joints = list(getattr(timber_model, "joints", None) or getattr(timber_model, "interactions", None) or [])
    joint_count = len(joints)
    joint_types = {}
    for joint in joints:
        joint_type = type(joint).__name__
        joint_types[joint_type] = joint_types.get(joint_type, 0) + 1
    joint_errors = [getattr(error, "debug_info", repr(error)) for error in joining_errors]

    # Rückgabe-Dictionary anpassen
    return {
        "plates": plates,
        "frame_beams": frame_beams,
        "plate_beams": plate_beams,
        "plates_out": plates_out,
        "frame_beams_out": frame_beams_out,
        "plate_beams_out": plate_beams_out,
        "plate_holes_out": plate_holes_out,
        "plate_holes_rhino": plate_holes_rhino,
        "plates_rhino": plates_rhino,
        "frame_beams_rhino": frame_beams_rhino,
        "plate_beams_rhino": plate_beams_rhino,
        "geometry_errors": geometry_errors,
        "joints": joints,
        "joint_count": joint_count,
        "joint_types": joint_types,
        "joint_errors": joint_errors,
        "joining_errors": joining_errors,
        "unjoined_clusters": unjoined_clusters,
        "timber_model": timber_model,
    }