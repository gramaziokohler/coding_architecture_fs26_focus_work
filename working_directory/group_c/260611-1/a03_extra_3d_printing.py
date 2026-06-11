import math

import Rhino.Geometry as rg
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Rotation
from compas.geometry import Scale
from compas.geometry import Transformation
from compas.geometry import Translation
from compas.geometry import Vector

# ==============================================================================
# 1. Preparation Module
# ==============================================================================


class PrintItem:
    def __init__(self, beam_id, beam_name, width, length, height, volume, base_transformation, original_beam):
        self.id = beam_id
        self.name = beam_name
        self.width = width  # Dimension X on plate
        self.length = length  # Dimension Y on plate
        self.height = height  # Dimension Z (Thickness)
        self.volume = volume  # Scaled volume
        self.base_transformation = base_transformation  # Transform: World -> Scaled & Oriented at Origin
        self.original_beam = original_beam  # Reference to original compas_timber beam
        self.final_rh_geo = None  # Store processed Rhino geometry (without engraving)
        self.text_3d_geo = None  # Store 3D text geometry for boolean/output
        self.text_2d_geo = None  # Store 2D text curves


def create_3d_text_engraving(text, text_height=5.0, engraving_depth=1.0):
    """
    Creates 3D text geometry and 2D curves using RhinoCommon's TextEntity.
    Uses large-scale generation and scales down to avoid Rhino's precision limits.
    """
    # 1. GENERATE AT LARGE SCALE (1000x)
    # Rhino's geometry engine (especially Join/Intersection) struggles below 0.001 units.
    # By working at 1000x scale and scaling down at the end, we bypass these limits.
    target_scale = 1.0
    work_scale = 1000.0
    scale_factor = work_scale / target_scale
    
    work_height = text_height * scale_factor
    work_depth = engraving_depth * scale_factor
    
    # Standard tolerances for large scale
    fine_tol = 0.001 
    boolean_tol = 0.01

    # Create text entity at large scale
    te = rg.TextEntity()
    te.Text = text
    te.Plane = rg.Plane.WorldXY
    te.FontIndex = 0
    te.TextHeight = work_height

    curves = te.Explode()
    if not curves:
        return None, None
    
    joined_curves = rg.Curve.JoinCurves(curves, fine_tol) or []
    
    text_breps = rg.Brep.CreatePlanarBreps(joined_curves, fine_tol)
    if not text_breps:
        return None, joined_curves
    
    solids = []
    for b in text_breps:
        for face in b.Faces:
            loops = [loop.To3dCurve() for loop in face.Loops]
            if not loops: continue
            
            ext = rg.Extrusion.Create(loops[0], work_depth, True)
            if ext:
                solid = ext.ToBrep()
                if len(loops) > 1:
                    for i in range(1, len(loops)):
                        inner_ext = rg.Extrusion.Create(loops[i], work_depth, True)
                        if inner_ext:
                            inner_solid = inner_ext.ToBrep()
                            if inner_solid:
                                diff = rg.Brep.CreateBooleanDifference(solid, inner_solid, boolean_tol)
                                if diff: solid = diff[0]
                solids.append(solid)
    
    final_3d = rg.Brep.MergeBreps(solids, boolean_tol)

    # 2. SCALE DOWN TO TARGET SIZE
    downscale = rg.Transform.Scale(rg.Plane.WorldXY, 1.0/scale_factor, 1.0/scale_factor, 1.0/scale_factor)
    
    if final_3d:
        final_3d.Transform(downscale)
    
    scaled_curves = []
    for crv in joined_curves:
        c = crv.DuplicateCurve()
        c.Transform(downscale)
        scaled_curves.append(c)

    return final_3d, scaled_curves


def prepare_beams_for_printing(timber_model, scale_factor=20.0, engraving=True, engraving_rel_depth=0.15, text_size_factor=0.8):
    """
    Prepares beams for printing by scaling and orienting.
    Engraving data is prepared but not subtracted.

    Args:
        text_size_factor: Controls size of labels (0.4 was previous default, 0.8 is double).
    """
    print_items = []
    scale = 1.0 / float(scale_factor)
    scale_xform = Scale.from_factors([scale, scale, scale])

    for i, beam in enumerate(timber_model.beams):
        geo = beam.geometry
        if not geo:
            continue

        try:
            # 1. Orientation and Scaling
            center = beam.frame.point
            to_origin = Translation.from_vector(Point(0, 0, 0) - center)
            align_rot = Transformation.from_frame_to_frame(beam.frame, Frame.worldXY())
            rotate_side = Rotation.from_axis_and_angle([1, 0, 0], math.radians(90))

            total_xform = scale_xform * rotate_side * align_rot * to_origin

            # 2. Conversion to Rhino
            m = total_xform.matrix
            rh_xform = rg.Transform.Identity
            for r in range(4):
                for c in range(4):
                    rh_xform[r, c] = float(m[r][c])

            # 2. Conversion to Rhino
            if hasattr(geo, "to_rhino"):
                rh_geo = geo.to_rhino()
            elif hasattr(geo, "to_brep"):
                rh_geo = geo.to_brep().to_rhino()
            elif type(geo).__name__.endswith("RhinoBrep"):
                rh_geo = getattr(geo, "brep", getattr(geo, "native_brep", getattr(geo, "_brep", None)))
            else:
                try:
                    rh_geo = geo.to_mesh().to_rhino()
                except:
                    rh_geo = rg.Mesh()

            if rh_geo:
                # 3. Dimensions and Centering
                rh_geo_trans = rh_geo.Duplicate()
                rh_geo_trans.Transform(rh_xform)

                bbox = rh_geo_trans.GetBoundingBox(True)
                dx, dy, dz = bbox.Max.X - bbox.Min.X, bbox.Max.Y - bbox.Min.Y, bbox.Max.Z - bbox.Min.Z

                # Center on XY plane at origin
                correction_vec = Vector(-(bbox.Max.X + bbox.Min.X) / 2.0, -(bbox.Max.Y + bbox.Min.Y) / 2.0, -bbox.Min.Z)
                total_xform = Translation.from_vector(correction_vec) * total_xform

                # Update final Rhino geometry
                m = total_xform.matrix
                for r in range(4):
                    for c in range(4):
                        rh_xform[r, c] = float(m[r][c])

                rh_geo_trans = rh_geo.Duplicate()
                rh_geo_trans.Transform(rh_xform)

                # 4. Preparation of Text (3D and 2D)
                beam_name = f"{i + 1:02d}"
                text_3d = None
                text_2d = None
                
                if engraving:
                    t_height = min(dx, dy) * text_size_factor
                    actual_depth = dz * engraving_rel_depth

                    text_3d, text_2d = create_3d_text_engraving(beam_name, text_height=t_height, engraving_depth=actual_depth)
                    if text_3d:
                        # Position text slightly embedded in the top surface
                        text_3d.Transform(rg.Transform.Translation(0, 0, dz - actual_depth * 0.8))
                    
                    if text_2d:
                        # Position curves on the top surface
                        text_2d_processed = []
                        move_up = rg.Transform.Translation(0, 0, dz)
                        for crv in text_2d:
                            crv_copy = crv.Duplicate()
                            crv_copy.Transform(move_up)
                            text_2d_processed.append(crv_copy)
                        text_2d = text_2d_processed

                # 5. Volume Calculation
                vmp = rg.VolumeMassProperties.Compute(rh_geo_trans)
                vol = vmp.Volume if vmp else 0.0

            else:
                raise Exception("Could not convert Compas geometry to Rhino")

            # Create Item
            item = PrintItem(beam_id=str(beam.guid), beam_name=beam_name, width=dx, length=dy, height=dz, volume=vol, base_transformation=total_xform, original_beam=beam)
            item.final_rh_geo = rh_geo_trans
            item.text_3d_geo = text_3d
            item.text_2d_geo = text_2d
            print_items.append(item)

        except Exception as e:
            print(f"Skipped Beam {i}: {type(e).__name__} - {e}")
            import traceback

            traceback.print_exc()

    return print_items


# ==============================================================================
# 2. Packing Module (The Logic)
# ==============================================================================


def solve_shelf_packing(print_items, plate_width, plate_length, spacing, gap_fill=True):
    """
    Packs 2D items onto fixed-size plates using a Shelf Algorithm (First Fit).

    Args:
        print_items: List of Printitem objects.
        plate_width: (float) X dimension of plate (in scaled units, e.g. meters).
        plate_length: (float) Y dimension of plate.
        spacing: (float) Minimum distance between items.

    Returns:
        dict: { plate_index: [ {'item': item, 'pose': Transformation} ] }
    """

    # Sort items by Height (which is Y-dim on plate) decreasing
    # This usually gives better shelf packing results.
    sorted_items = sorted(print_items, key=lambda x: x.length, reverse=True)

    plates = {}  # Key: int index, Value: list of placed dicts

    # Internal state for current packing
    current_plate_idx = 0
    current_x = spacing
    current_y = spacing
    current_shelf_height = 0.0

    # Initialize first plate
    plates[0] = []

    for item in sorted_items:
        # Dimensions including spacing (we only add spacing after, but check bounds)
        w = item.width
        l = item.length  # 'Height' on the 2D plan

        # Check if fits in current shelf (Width-wise)
        if current_x + w + spacing > plate_width:
            # Move to next shelf -> Y increment
            current_y += current_shelf_height + spacing
            current_x = spacing
            current_shelf_height = 0.0  # Reset for new shelf

        # Check if fits in current plate (Length-wise / Y-axis)
        if current_y + l + spacing > plate_length:
            # New Plate
            current_plate_idx += 1
            plates[current_plate_idx] = []

            # Reset Cursor
            current_x = spacing
            current_y = spacing
            current_shelf_height = 0.0

        target_x = current_x + w / 2
        target_y = current_y + l / 2

        placement_xform = Translation.from_vector([target_x, target_y, 0])

        plates[current_plate_idx].append({"item": item, "pose": placement_xform})

        # Update Cursor
        current_x += w + spacing
        current_shelf_height = max(current_shelf_height, l)

    return plates


# ==============================================================================
# 3. Visualization & Stats Module
# ==============================================================================


def visualize_print_setup(packed_plates, plate_width, plate_length, plate_dist=0.5):
    """
    Creates Rhino-compatible geometry for the packing.
    Draws plates linearly in X direction.
    Returns: visual_meshes, visual_curves, visual_texts, visual_3d_texts, visual_2d_text_curves
    """
    visual_meshes = []
    visual_curves = []  # Plate boundaries
    visual_texts = []   # Label text and location
    visual_3d_texts = [] # 3D Brep text
    visual_2d_text_curves = [] # 2D Curves for text

    for p_idx, placed_items in packed_plates.items():
        # Offset for this plate
        plate_origin_x = p_idx * (plate_width + plate_dist)
        plate_offset = Translation.from_vector([plate_origin_x, 0, 0])

        # 1. Draw Plate Boundary
        pt0 = Point(0, 0, 0)
        pt1 = Point(plate_width, 0, 0)
        pt2 = Point(plate_width, plate_length, 0)
        pt3 = Point(0, plate_length, 0)

        # Transform points to plate location
        boundary_pts = [pt.transformed(plate_offset) for pt in [pt0, pt1, pt2, pt3, pt0]]
        rh_pts = [rg.Point3d(p.x, p.y, p.z) for p in boundary_pts]
        visual_curves.append(rg.Polyline(rh_pts).ToNurbsCurve())

        # Label Plate
        label_pt = boundary_pts[3]
        visual_texts.append((f"Plate {p_idx + 1}", rg.Point3d(label_pt.x, label_pt.y, label_pt.z)))

        # 2. Draw Items
        for entry in placed_items:
            item = entry["item"]
            pose = entry["pose"]  # Local placement on plate

            # Combine plate placement transforms
            layout_xform = plate_offset * pose

            # Convert to Rhino
            m = layout_xform.matrix
            rh_layout_xform = rg.Transform.Identity
            for r in range(4):
                for c in range(4):
                    rh_layout_xform[r, c] = float(m[r][c])

            # 1. Transform main geometry
            if item.final_rh_geo:
                layout_mesh = item.final_rh_geo.Duplicate()
                layout_mesh.Transform(rh_layout_xform)
                visual_meshes.append(layout_mesh)

            # 2. Transform 3D text
            if item.text_3d_geo:
                layout_3d_text = item.text_3d_geo.Duplicate()
                layout_3d_text.Transform(rh_layout_xform)
                visual_3d_texts.append(layout_3d_text)

            # 3. Transform 2D text curves
            if item.text_2d_geo:
                for crv in item.text_2d_geo:
                    layout_2d_crv = crv.Duplicate()
                    layout_2d_crv.Transform(rh_layout_xform)
                    visual_2d_text_curves.append(layout_2d_crv)

            # Label Item (for screen visualization)
            center = Point(0, 0, 0).transformed(plate_offset * pose)
            label_pos = rg.Point3d(center.x, center.y, center.z)
            visual_texts.append((item.name, label_pos))

    return visual_meshes, visual_curves, visual_texts, visual_3d_texts, visual_2d_text_curves

    return visual_meshes, visual_curves, visual_texts


def get_print_stats(packed_plates, duration_per_mm3=0.01, cost_per_mm3=0.005):
    """
    Calculates stats based on packed items.
    """
    total_volume = 0.0
    total_items = 0
    plate_count = len(packed_plates)

    for p_idx, items in packed_plates.items():
        for entry in items:
            total_items += 1
            total_volume += entry["item"].volume

    # Volume is in Model Units (scaled).
    # If Model is meters, volume is m3.
    # User params are per mm3.
    # 1 m3 = 1e9 mm3.

    vol_mm3 = total_volume * 1e9

    est_duration_min = vol_mm3 * duration_per_mm3
    est_duration_h = est_duration_min / 60.0

    est_cost = vol_mm3 * cost_per_mm3

    report = []
    report.append("--- 3D Printing Report ---")
    report.append(f"Total Beams: {total_items}")
    report.append(f"Used Plates: {plate_count}")
    report.append(f"Total Layout Volume: {total_volume:.6f} m3 ({vol_mm3:.0f} mm3)")
    report.append("-" * 20)
    report.append(f"Est. Duration: {est_duration_h:.1f} hours ({est_duration_min:.0f} min)")
    report.append(f"Est. Cost: {est_cost:.2f} CHF")
    report.append("-" * 20)
    report.append(f"Params: {duration_per_mm3} min/mm3, {cost_per_mm3} $/mm3")

    return "\n".join(report)


# ==============================================================================
# Helper for Grasshopper
# ==============================================================================
def convert_compas_to_rhino_mesh(compas_geo):
    """Fallback helper."""
    # This might depend on what compas_geo actually is (Brep, Mesh, Box)
    try:
        if hasattr(compas_geo, "to_rhino"):
            return compas_geo.to_rhino()
    except:
        pass
    return None
