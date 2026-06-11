"""
Bereinigte Stencil-Helper für COMPAS Timber.
Verhindert Kurven-Duplizierung und erzwingt physische Löcher in Platten.
"""

import math
from compas.geometry import Frame, Line, Point, Polyline, Vector
from compas.scene import SceneObject
from compas_timber.connections import JointTopology, LLapJoint, TLapJoint, XLapJoint
from compas_timber.elements import Beam, Plate
from compas_timber.model import TimberModel
from timber_design.workflow import JointRuleSolver, TopologyRule


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


def hole_openings_for_plate(rectangle, points, hole_radius, hole_segments):
    """Projiziert Punkte auf die Platte und erstellt die Kreise OHNE Duplizierung."""
    frame = rectangle_frame(rectangle)
    openings = []

    for point in points or []:
        compas_point = point_to_compas(point)
        # Punkt auf die lokale Plattenebene projizieren (Z=0)
        local_point = frame.to_local_coordinates(compas_point)
        
        # Nur Punkte nehmen, die auch wirklich auf der Platte liegen
        if rectangle.Contains(point) != 0:
            local_point.z = 0.0
            global_center = frame.to_global_coordinates(local_point)
            openings.append(circle_polyline(frame, global_center, hole_radius, hole_segments))

    return openings


def make_plate(rectangle, points, plate_thickness, hole_radius, hole_segments):
    return Plate.from_outline_thickness(
        rectangle_outline(rectangle),
        plate_thickness,
        vector=rectangle_frame(rectangle).zaxis,
        openings=hole_openings_for_plate(rectangle, points, hole_radius, hole_segments),
    )


def make_beam(line, beam_width, beam_height):
    return Beam.from_centerline(
        line_to_compas(line),
        width=beam_width,
        height=beam_height,
        z_vector=Vector(0, 0, 1),
    )


def element_geometry(element, errors, compute_plate_geometry=True):
    """Gibt das fertige Mesh inklusive aller Features (Löcher) zurück."""
    if isinstance(element, Plate) and not compute_plate_geometry:
        try:
            return element.blank.to_mesh()
        except Exception as error:
            errors.append("Plate blank preview: {!r}".format(error))

    try:
        # .geometry erzwingt bei COMPAS das Ausstanzen der Löcher im Mesh
        return element.geometry
    except Exception as error:
        errors.append("{} geometry error: {!r}".format(type(element).__name__, error))
        if isinstance(element, Plate):
            try:
                geom = element.compute_elementgeometry(include_features=True)
                return geom.transformed(element.modeltransformation)
            except Exception:
                pass
            return element.blank.to_mesh()
        return None


def rhino_geometry(geometry, errors):
    if geometry is None:
        return None
    try:
        return SceneObject(item=geometry).draw()
    except Exception as error:
        errors.append("Rhino conversion: {}".format(error))
        return None


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
    plate_beam_width=0.090,
    plate_beam_height=0.090,
    joint_max_distance=0.020,
    lap_cut_plane_bias=0.5,
    flip_lap_side=False,
    include_x_lap=True,
    process_joinery=False,
    compute_plate_geometry=True,
):
    rectangles = rectangles or []
    points = points or []
    frame_beam_lines = frame_beam_lines or []
    plate_beam_lines = plate_beam_lines or []

    # 1. Platten mit zugeordneten Löchern erstellen
    plates = [
        make_plate(rect, points, plate_thickness, hole_radius, hole_segments)
        for rect in rectangles
    ]
    
    # 2. Balken getrennt erstellen
    frame_beams = [make_beam(l, frame_beam_width, frame_beam_height) for l in frame_beam_lines]
    plate_beams = [make_beam(l, plate_beam_width, plate_beam_height) for l in plate_beam_lines]
    beams = frame_beams + plate_beams

    # 3. Model befüllen
    timber_model = TimberModel()
    for plate in plates:
        timber_model.add_element(plate)
    for beam in beams:
        timber_model.add_element(beam)

    # 4. Verbindungen berechnen
    rules = [
        TopologyRule(JointTopology.TOPO_T, TLapJoint, max_distance=joint_max_distance, cut_plane_bias=lap_cut_plane_bias, flip_lap_side=flip_lap_side),
        TopologyRule(JointTopology.TOPO_L, LLapJoint, max_distance=joint_max_distance, cut_plane_bias=lap_cut_plane_bias, flip_lap_side=flip_lap_side)
    ]
    if include_x_lap:
        rules.append(TopologyRule(JointTopology.TOPO_X, XLapJoint, max_distance=joint_max_distance, cut_plane_bias=lap_cut_plane_bias, flip_lap_side=flip_lap_side))
    
    solver = JointRuleSolver(rules)
    joining_errors, unjoined_clusters = solver.apply_rules_to_model(timber_model)

    if process_joinery:
        timber_model.process_joinery()

    # 5. Geometrie-Ausgaben erzeugen
    geometry_errors = []
    plates_out = [element_geometry(p, geometry_errors, compute_plate_geometry) for p in plates]
    frame_beams_out = [element_geometry(b, geometry_errors) for b in frame_beams]
    plate_beams_out = [element_geometry(b, geometry_errors) for b in plate_beams]
    
    plates_rhino = [rhino_geometry(g, geometry_errors) for g in plates_out]
    frame_beams_rhino = [rhino_geometry(g, geometry_errors) for g in frame_beams_out]
    plate_beams_rhino = [rhino_geometry(g, geometry_errors) for g in plate_beams_out]

    # Loch-Kurven (Exakt 1x pro Punkt, da direkt aus den berechneten Platten-Openings ausgelesen)
    plate_holes_out = []
    for plate in plates:
        for opening in plate.plate_geometry.openings:
            plate_holes_out.append(opening.transformed(plate.modeltransformation))
    plate_holes_rhino = [rhino_geometry(h, geometry_errors) for h in plate_holes_out]

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
        "timber_model": timber_model,
        "joints": list(getattr(timber_model, "joints", None) or []),
        "joint_count": len(list(getattr(timber_model, "joints", None) or [])),
        "joint_types": {},
        "joint_errors": [repr(e) for e in joining_errors],
        "joining_errors": joining_errors,
        "unjoined_clusters": unjoined_clusters,
    }