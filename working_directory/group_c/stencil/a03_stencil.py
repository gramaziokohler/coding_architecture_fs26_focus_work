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
    frame = rectangle_frame(rectangle)
    
    # 1. Wir generieren die Platte direkt über die Openings-Logik.
    # COMPAS nutzt hierbei die 2D-Polylines, um das 3D-Mesh mit Löchern zu generieren.
    plate = Plate.from_outline_thickness(
        rectangle_outline(rectangle),
        plate_thickness,
        vector=frame.zaxis,
        openings=hole_openings(rectangle, points, hole_radius, hole_segments),
    )
    
    # ZWANGS-GENERIERUNG: Wir zwingen das Element hier dazu, seine 
    # interne Geometrie inklusive der Löcher sofort zu berechnen!
    try:
        # Das triggert die boolesche Subtraktion der Openings im COMPAS-Kern
        plate.geometry = plate.compute_elementgeometry(include_features=True)
    except Exception:
        # Fallback, falls die Eigenschaft in deiner Version schreibgeschützt ist
        pass

    return plate


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
    # Wenn es eine Platte ist, wollen wir das fertige Mesh inklusive Löchern!
    if isinstance(element, Plate):
        try:
            # Wir versuchen explizit die Geometrie MIT den Openings/Features abzurufen
            if hasattr(element, "compute_elementgeometry"):
                return element.compute_elementgeometry(include_features=True)
            return element.geometry
        except Exception as error:
            errors.append("Plate geometry generation failed: {!r}".format(error))
            
    # Standard-Verhalten für Balken und Fallbacks
    try:
        return element.geometry
    except Exception as error:
        errors.append("{} geometry: {!r}".format(type(element).__name__, error))
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
    frame_beam_lines=None,
    plate_beam_lines=None,
    plate_thickness=0.010,
    hole_radius=0.015,
    hole_segments=24,
    frame_beam_width=0.060,
    frame_beam_height=0.080,
    plate_beam_width=0.040,   # Auf Standard-Fallback aus GH angepasst
    plate_beam_height=0.060,  # Auf Standard-Fallback aus GH angepasst
    joint_max_distance=0.020,
    tbutt_mill_depth=0.001,
    lap_cut_plane_bias=0.5,
    flip_lap_side=False,
    include_x_lap=True,
    process_joinery=False,
    compute_plate_geometry=True, # NEU: Standardmäßig True, um Löcher in 3D zu stanzen
):
    """Create plates, beams, lap joints, and preview geometry with mixed beam sizes."""

    rectangles = rectangles or []
    points = points or []
    frame_beam_lines = frame_beam_lines or []
    plate_beam_lines = plate_beam_lines or []

    # 1. Platten erstellen (nutzt intern die sichere try-except Logik)
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

    # Verbindungen berechnen
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
    geometry_errors = []
    
    # Hier werden nun die echten 3D-Platten mit Löchern berechnet
    plates_out = [element_geometry(plate, geometry_errors, compute_plate_geometry) for plate in plates]
    
    # Ausgaben für Rhino getrennt berechnen
    frame_beams_out = [element_geometry(beam, geometry_errors) for beam in frame_beams]
    plate_beams_out = [element_geometry(beam, geometry_errors) for beam in plate_beams]
    
    frame_beams_rhino = [rhino_geometry(geom, geometry_errors) for geom in frame_beams_out]
    plate_beams_rhino = [rhino_geometry(geom, geometry_errors) for geom in plate_beams_out]

    # NEU: Löcher für die 2D-Vorschau ohne 4-fach Duplikate sammeln
    plate_holes_out = []
    seen_centers = []

    for plate in plates:
        for opening in plate.plate_geometry.openings:
            ref_pt = opening.points[0]  # Das ist der Punkt
            
            # Wir holen uns einfach die nackten Zahlen (X und Y Koordinaten)
            x1, y1 = ref_pt.x, ref_pt.y
            
            # Wir prüfen, ob wir schon einen Punkt haben, der fast identisch ist
            is_duplicate = False
            for seen in seen_centers:
                x2, y2 = seen.x, seen.y
                # Distanzberechnung per Pythagoras: c = sqrt((x1-x2)^2 + (y1-y2)^2)
                distance_squared = (x1 - x2)**2 + (y1 - y2)**2
                if distance_squared < 0.0001:  # Wenn der Abstand winzig ist, ist es ein Duplikat
                    is_duplicate = True
                    break
            
            # Nur hinzufügen, wenn es kein Duplikat ist
            if not is_duplicate:
                plate_holes_out.append(opening.transformed(plate.modeltransformation))
                seen_centers.append(ref_pt)

    # In Rhino-Geometrie umwandeln
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

    # Rückgabe-Dictionary
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