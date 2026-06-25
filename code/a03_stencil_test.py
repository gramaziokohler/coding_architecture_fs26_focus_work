"""
Stencil helpers for plates with circular openings and mixed timber beams.
"""

import math

import Rhino
import Rhino.Geometry as rg

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
from compas_timber.fabrication import Drilling
from compas_timber.elements import Beam
from compas_timber.elements import Plate
from compas_timber.model import TimberModel
from timber_design.workflow import JointRuleSolver
from timber_design.workflow import TopologyRule


class StencilPlate(Plate):
    @property
    def features(self):
        return self._features

    @features.setter
    def features(self, features):
        self._features = features

    @property
    def __dtype__(self):
        return "compas_timber.elements/Plate"


# =============================================================================
# BASIC CONVERSIONS
# =============================================================================

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


def project_point_to_rectangle_plane(rectangle, point):
    plane = rectangle.Plane
    normal = rg.Vector3d(plane.ZAxis)
    normal.Unitize()

    vec = point - plane.Origin
    distance = rg.Vector3d.Multiply(vec, normal)

    return rg.Point3d(
        point.X - normal.X * distance,
        point.Y - normal.Y * distance,
        point.Z - normal.Z * distance,
    )


def point_in_rectangle(rectangle, point):
    if point is None:
        return False
    point = project_point_to_rectangle_plane(rectangle, point)
    return rectangle.Contains(point) != 0


def points_in_rectangle(rectangle, points):
    return [
        point
        for point in points or []
        if point_in_rectangle(rectangle, point)
    ]


# =============================================================================
# COMPAS OPENINGS
# =============================================================================

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

        center = point_to_compas(project_point_to_rectangle_plane(rectangle, point))
        openings.append(circle_polyline(frame, center, hole_radius, hole_segments))

    return openings


def hole_drilling_lines(rectangle, points, plate_thickness=0.010):
    frame = rectangle_frame(rectangle)
    normal = frame.zaxis.unitized()
    line_extension = max(plate_thickness * 2.0, 0.001)
    drilling_lines = []

    for point in points or []:
        if not point_in_rectangle(rectangle, point):
            continue

        center = point_to_compas(project_point_to_rectangle_plane(rectangle, point))
        drilling_lines.append(
            Line(
                center + normal * line_extension,
                center - normal * line_extension,
            )
        )

    return drilling_lines


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


def add_drilling_features(plate, drilling_lines, diameter, errors=None):
    drillings = []
    errors = errors if errors is not None else []

    for line in drilling_lines or []:
        try:
            drilling = Drilling.from_line_and_element(line, plate, diameter)
            if hasattr(plate, "add_feature"):
                plate.add_feature(drilling)
            else:
                plate.features.append(drilling)
            drillings.append(drilling)
        except Exception as error:
            errors.append("Plate drilling: {!r}".format(error))

    return drillings


def clear_cached_geometry(elements):
    for element in elements or []:
        if hasattr(element, "_geometry"):
            element._geometry = None


def make_standalone_holes(points, rectangles, hole_radius=0.015, hole_segments=24):
    """Generates the circle polylines independently of the plate objects."""
    if not points:
        return []

    if rectangles and len(rectangles) > 0:
        frame = rectangle_frame(rectangles[0])
    else:
        frame = Frame.world_xy()

    hole_curves = []
    for point in points:
        center = point_to_compas(point)
        hole_curves.append(circle_polyline(frame, center, hole_radius, hole_segments))

    return hole_curves


# =============================================================================
# RHINO BREPS FOR PHYSICAL VOLUMES
# =============================================================================

def rhino_tolerance(default=0.0001):
    try:
        doc = Rhino.RhinoDoc.ActiveDoc
        if doc:
            return doc.ModelAbsoluteTolerance
    except Exception:
        pass
    return default


def scaled_vector(vector, scale):
    return rg.Vector3d(vector.X * scale, vector.Y * scale, vector.Z * scale)


def shifted_point(point, vector, distance):
    return rg.Point3d(
        point.X + vector.X * distance,
        point.Y + vector.Y * distance,
        point.Z + vector.Z * distance,
    )


def project_point_to_plane(point, plane):
    """Projects a Rhino point exactly onto a Rhino plane."""
    normal = rg.Vector3d(plane.ZAxis)
    normal.Unitize()

    vec = point - plane.Origin
    distance = rg.Vector3d.Multiply(vec, normal)

    return rg.Point3d(
        point.X - normal.X * distance,
        point.Y - normal.Y * distance,
        point.Z - normal.Z * distance,
    )


def rectangle_rhino_curve(rectangle):
    corners = [rectangle.Corner(i) for i in range(4)]
    corners.append(rectangle.Corner(0))
    return rg.PolylineCurve(corners)


def hole_rhino_curves(rectangle, points, hole_radius=0.015):
    """Creates planar Rhino circle curves for all holes inside one rectangle."""
    plane = rectangle.Plane
    curves = []

    for point in points or []:
        if not point_in_rectangle(rectangle, point):
            continue

        center = project_point_to_plane(point, plane)
        hole_plane = rg.Plane(center, plane.XAxis, plane.YAxis)

        circle = rg.Circle(hole_plane, hole_radius)
        curves.append(circle.ToNurbsCurve())

    return curves


def extrude_closed_curve_to_brep(curve, direction, tolerance):
    surface = rg.Surface.CreateExtrusion(curve, direction)
    if surface is None:
        return None

    brep = surface.ToBrep()
    if brep is None:
        return None

    capped = brep.CapPlanarHoles(tolerance)
    return capped if capped else brep


def make_hole_volume_breps(
    rectangle,
    points,
    hole_radius=0.015,
    plate_thickness=0.010,
    start_offset=0.0,
    depth=None,
    tolerance=None,
):
    """
    Creates Rhino Brep cylinders for the hole volumes.
    These are the physical volumes of the material missing from the plate.
    """
    tolerance = tolerance or rhino_tolerance()

    if depth is None:
        depth = plate_thickness

    plane = rectangle.Plane
    normal = rg.Vector3d(plane.ZAxis)
    normal.Unitize()

    direction = scaled_vector(normal, depth)

    breps = []

    for point in points or []:
        if not point_in_rectangle(rectangle, point):
            continue

        projected = project_point_to_plane(point, plane)
        base_point = shifted_point(projected, normal, start_offset)
        hole_plane = rg.Plane(base_point, plane.XAxis, plane.YAxis)

        circle = rg.Circle(hole_plane, hole_radius)
        curve = circle.ToNurbsCurve()

        brep = extrude_closed_curve_to_brep(curve, direction, tolerance)
        if brep:
            breps.append(brep)

    return breps


def make_plate_brep_with_holes(
    rectangle,
    points,
    plate_thickness=0.010,
    hole_radius=0.015,
    tolerance=None,
    errors=None,
):
    """
    Creates a Rhino Brep plate volume with real physical holes.

    Important:
    This version does NOT use BooleanDifference.
    It creates a planar Brep from:
        outer rectangle + inner circular holes
    and then offsets/extrudes that face into a solid.
    """
    tolerance = tolerance or rhino_tolerance()
    errors = errors if errors is not None else []

    outer_curve = rectangle_rhino_curve(rectangle)
    inner_curves = hole_rhino_curves(
        rectangle=rectangle,
        points=points,
        hole_radius=hole_radius,
    )

    curves = [outer_curve] + inner_curves

    planar_breps = rg.Brep.CreatePlanarBreps(curves, tolerance)

    if not planar_breps or len(planar_breps) == 0:
        errors.append("CreatePlanarBreps failed. Returning uncut rectangular plate.")

        plane = rectangle.Plane
        normal = rg.Vector3d(plane.ZAxis)
        normal.Unitize()

        direction = scaled_vector(normal, plate_thickness)
        fallback = extrude_closed_curve_to_brep(outer_curve, direction, tolerance)

        return [fallback] if fallback else []

    # Pick the largest planar region.
    # This avoids accidentally taking one of the circular hole disks.
    largest_brep = None
    largest_area = -1.0

    for brep in planar_breps:
        amp = rg.AreaMassProperties.Compute(brep)
        if amp and amp.Area > largest_area:
            largest_area = amp.Area
            largest_brep = brep

    if largest_brep is None:
        errors.append("Could not identify largest planar Brep region.")
        return []

    face = largest_brep.Faces[0]

    try:
        solid = rg.Brep.CreateFromOffsetFace(
            face,
            plate_thickness,
            tolerance,
            False,
            True,
        )

        if solid:
            return [solid]

        errors.append("CreateFromOffsetFace failed. Returning planar Brep only.")
        return [largest_brep]

    except Exception as error:
        errors.append("CreateFromOffsetFace error: {!r}".format(error))
        return [largest_brep]


# =============================================================================
# JOINERY
# =============================================================================

def add_lap_joints(
    model,
    joint_max_distance=0.020,
    lap_cut_plane_bias=0.5,
    flip_lap_side=False,
    include_x_lap=True,
):
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
        ),
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


# =============================================================================
# GEOMETRY OUTPUT
# =============================================================================

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


# =============================================================================
# MAIN FUNCTION
# =============================================================================

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
    plate_beam_width=0.040,
    plate_beam_height=0.060,
    joint_max_distance=0.020,
    tbutt_mill_depth=0.001,
    lap_cut_plane_bias=0.5,
    flip_lap_side=False,
    include_x_lap=True,
    process_joinery=False,
    compute_plate_geometry=False,
    hole_processing="free_contour",
):
    """Create plates, beams, lap joints, physical hole volumes, and preview geometry."""
    rectangles = rectangles or []
    points = points or []
    frame_beam_lines = frame_beam_lines or []
    plate_beam_lines = plate_beam_lines or []
    hole_processing = (hole_processing or "free_contour").lower()
    if hole_processing in ("freecontour", "contour", "openings"):
        hole_processing = "free_contour"
    if hole_processing not in ("free_contour", "drilling", "none"):
        hole_processing = "free_contour"

    points_by_plate = [
        points_in_rectangle(rectangle, points)
        for rectangle in rectangles
    ]

    # -------------------------------------------------------------------------
    # 1. COMPAS plates with encoded openings
    # -------------------------------------------------------------------------

    plate_openings_by_plate = [
        hole_openings(
            rectangle,
            plate_points,
            hole_radius=hole_radius,
            hole_segments=hole_segments,
        )
        for rectangle, plate_points in zip(rectangles, points_by_plate)
    ]
    model_openings_by_plate = (
        plate_openings_by_plate
        if hole_processing == "free_contour"
        else [[] for _ in rectangles]
    )

    plate_cls = StencilPlate if hole_processing == "drilling" else Plate
    plates = [
        plate_cls.from_outline_thickness(
            rectangle_outline(rectangle),
            plate_thickness,
            vector=rectangle_frame(rectangle).zaxis,
            openings=openings,
        )
        for rectangle, openings in zip(rectangles, model_openings_by_plate)
    ]
    plate_drilling_lines_by_plate = [
        hole_drilling_lines(
            rectangle,
            plate_points,
            plate_thickness=plate_thickness,
        )
        for rectangle, plate_points in zip(rectangles, points_by_plate)
    ]
    plate_drillings_by_plate = [[] for _ in plates]

    # -------------------------------------------------------------------------
    # 2. Beams
    # -------------------------------------------------------------------------

    frame_beams = [
        make_beam(
            line,
            beam_width=frame_beam_width,
            beam_height=frame_beam_height,
        )
        for line in frame_beam_lines
    ]

    plate_beams = [
        make_beam(
            line,
            beam_width=plate_beam_width,
            beam_height=plate_beam_height,
        )
        for line in plate_beam_lines
    ]

    beams = frame_beams + plate_beams

    # -------------------------------------------------------------------------
    # 3. Timber model
    # -------------------------------------------------------------------------

    timber_model = TimberModel()

    geometry_errors = []

    if hole_processing == "drilling":
        plate_drillings_by_plate = [
            add_drilling_features(
                plate,
                drilling_lines,
                diameter=hole_radius * 2.0,
                errors=geometry_errors,
            )
            for plate, drilling_lines in zip(plates, plate_drilling_lines_by_plate)
        ]

    for plate in plates:
        timber_model.add_element(plate)

    for beam in beams:
        timber_model.add_element(beam)

    joining_errors, unjoined_clusters = add_lap_joints(
        timber_model,
        joint_max_distance=joint_max_distance,
        lap_cut_plane_bias=lap_cut_plane_bias,
        flip_lap_side=flip_lap_side,
        include_x_lap=include_x_lap,
    )

    if process_joinery:
        timber_model.process_joinery()

    # -------------------------------------------------------------------------
    # 4. COMPAS geometry output
    # -------------------------------------------------------------------------

    plates_out = [
        element_geometry(
            plate,
            geometry_errors,
            compute_plate_geometry=compute_plate_geometry,
        )
        for plate in plates
    ]

    frame_beams_out = [
        element_geometry(beam, geometry_errors)
        for beam in frame_beams
    ]

    plate_beams_out = [
        element_geometry(beam, geometry_errors)
        for beam in plate_beams
    ]

    frame_beams_rhino = [
        rhino_geometry(geom, geometry_errors)
        for geom in frame_beams_out
    ]

    plate_beams_rhino = [
        rhino_geometry(geom, geometry_errors)
        for geom in plate_beams_out
    ]

    plates_rhino = [
        rhino_geometry(geometry, geometry_errors)
        for geometry in plates_out
    ]

    # -------------------------------------------------------------------------
    # 5. Flatten COMPAS openings / curves
    # -------------------------------------------------------------------------

    plate_holes_by_plate = []
    plate_holes_out = []

    for openings in plate_openings_by_plate:
        plate_holes_by_plate.append(list(openings))
        plate_holes_out.extend(openings)

    plate_holes_rhino = [
        rhino_geometry(hole, geometry_errors)
        for hole in plate_holes_out
    ]

    # -------------------------------------------------------------------------
    # 6. Rhino Brep output: exact missing hole volumes
    # -------------------------------------------------------------------------

    hole_volumes_by_plate = [
        make_hole_volume_breps(
            rectangle=rectangle,
            points=plate_points,
            hole_radius=hole_radius,
            plate_thickness=plate_thickness,
            start_offset=0.0,
            depth=plate_thickness,
        )
        for rectangle, plate_points in zip(rectangles, points_by_plate)
    ]

    hole_volumes_out = []

    for volumes in hole_volumes_by_plate:
        hole_volumes_out.extend(volumes)

    # -------------------------------------------------------------------------
    # 7. Rhino Brep output: physical plates with holes
    # -------------------------------------------------------------------------

    plates_brep_by_plate = [
        make_plate_brep_with_holes(
            rectangle=rectangle,
            points=plate_points,
            plate_thickness=plate_thickness,
            hole_radius=hole_radius,
            errors=geometry_errors,
        )
        for rectangle, plate_points in zip(rectangles, points_by_plate)
    ]

    plates_brep_out = []

    for plate_breps in plates_brep_by_plate:
        plates_brep_out.extend(plate_breps)

    if hole_processing == "drilling":
        clear_cached_geometry(plates)

    # -------------------------------------------------------------------------
    # 8. Joint stats
    # -------------------------------------------------------------------------

    joints = list(
        getattr(timber_model, "joints", None)
        or getattr(timber_model, "interactions", None)
        or []
    )

    joint_count = len(joints)

    joint_types = {}

    for joint in joints:
        joint_type = type(joint).__name__
        joint_types[joint_type] = joint_types.get(joint_type, 0) + 1

    joint_errors = [
        getattr(error, "debug_info", repr(error))
        for error in joining_errors
    ]

    # -------------------------------------------------------------------------
    # 9. Return
    # -------------------------------------------------------------------------

    return {
        "plates": plates,
        "frame_beams": frame_beams,
        "plate_beams": plate_beams,

        "plates_out": plates_out,
        "frame_beams_out": frame_beams_out,
        "plate_beams_out": plate_beams_out,

        "plates_brep_out": plates_brep_out,
        "plates_brep_by_plate": plates_brep_by_plate,

        "plate_holes_out": plate_holes_out,
        "plate_holes_rhino": plate_holes_rhino,

        "plate_holes_by_plate": plate_holes_by_plate,
        "plate_openings": model_openings_by_plate,
        "plate_openings_by_plate": model_openings_by_plate,
        "plate_preview_holes_by_plate": plate_openings_by_plate,
        "points_by_plate": points_by_plate,
        "hole_processing": hole_processing,
        "plate_drilling_lines_by_plate": plate_drilling_lines_by_plate,
        "plate_drillings_by_plate": plate_drillings_by_plate,

        "hole_volumes_out": hole_volumes_out,
        "hole_volumes_by_plate": hole_volumes_by_plate,

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
