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
        self.width = width
        self.length = length
        self.height = height
        self.volume = volume
        self.base_transformation = base_transformation
        self.original_beam = original_beam
        self.final_rh_geo = None
        self.text_3d_geo = None
        self.text_2d_geo = None

def create_3d_text_engraving(text, text_height=5.0, engraving_depth=1.0):
    """
    Creates 3D text geometry and 2D curves using RhinoCommon's TextEntity.
    Uses large-scale generation and scales down to avoid Rhino's precision limits.
    """
    target_scale = 1.0
    work_scale = 1000.0
    scale_factor = work_scale / target_scale

    work_height = text_height * scale_factor
    work_depth = engraving_depth * scale_factor

    fine_tol = 0.001
    boolean_tol = 0.01

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
            if not loops:
                continue

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
                                if diff:
                                    solid = diff[0]
                solids.append(solid)

    final_3d = rg.Brep.MergeBreps(solids, boolean_tol)

    downscale = rg.Transform.Scale(rg.Plane.WorldXY, -1.0/scale_factor, 1.0/scale_factor, 1.0/scale_factor)

    if final_3d:
        final_3d.Transform(downscale)

    scaled_curves = []
    for crv in joined_curves:
        c = crv.DuplicateCurve()
        c.Transform(downscale)
        scaled_curves.append(c)

    return final_3d, scaled_curves


def prepare_beams_for_printing(timber_model, scale_factor=20.0, engraving=True, engraving_rel_depth=0.15, text_size_factor=0.8):
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

                correction_vec = Vector(-(bbox.Max.X + bbox.Min.X) / 2.0, -(bbox.Max.Y + bbox.Min.Y) / 2.0, -bbox.Min.Z)
                total_xform = Translation.from_vector(correction_vec) * total_xform

                m = total_xform.matrix
                for r in range(4):
                    for c in range(4):
                        rh_xform[r, c] = float(m[r][c])

                rh_geo_trans = rh_geo.Duplicate()
                rh_geo_trans.Transform(rh_xform)

                # ── ROTAZIONE 90° attorno a X (beam + testo insieme) ──
                bbox_before = rh_geo_trans.GetBoundingBox(True)
                cx = (bbox_before.Max.X + bbox_before.Min.X) / 2.0
                cy = (bbox_before.Max.Y + bbox_before.Min.Y) / 2.0
                cz = (bbox_before.Max.Z + bbox_before.Min.Z) / 2.0
                rot90 = rg.Transform.Rotation(
                    math.radians(90),
                    rg.Vector3d.XAxis,
                    rg.Point3d(cx, cy, cz)
                )
                rh_geo_trans.Transform(rot90)

                # Ricalcola bbox e dimensioni dopo rotazione
                bbox = rh_geo_trans.GetBoundingBox(True)
                dx, dy, dz = bbox.Max.X - bbox.Min.X, bbox.Max.Y - bbox.Min.Y, bbox.Max.Z - bbox.Min.Z

                # 4. Preparation of Text (3D and 2D)
                if hasattr(beam, 'name') and beam.name and not str(beam.name).isdigit():
                    beam_name = str(beam.name)
                else:
                    beam_name = f"{i + 1:02d}"

                text_3d = None
                text_2d = None

                if engraving:
                    FACCIA_DESTINAZIONE = "fianco_sinistro"

                    if FACCIA_DESTINAZIONE in ["fianco_destro", "fianco_sinistro"]:
                        t_height = min(dx, dz) * text_size_factor
                        actual_depth = dy * engraving_rel_depth
                    else:
                        t_height = min(dx, dy) * text_size_factor
                        actual_depth = dz * engraving_rel_depth

                    text_3d, text_2d = create_3d_text_engraving(beam_name, text_height=t_height, engraving_depth=actual_depth)

                    if text_3d:
                        text_bbox = text_3d.GetBoundingBox(True)
                        text_dx = text_bbox.Max.X - text_bbox.Min.X
                        text_dy = text_bbox.Max.Y - text_bbox.Min.Y
                        text_dz = text_bbox.Max.Z - text_bbox.Min.Z

                        base_x = -(text_bbox.Min.X + text_dx / 2.0)
                        base_y = -(text_bbox.Min.Y + text_dy / 3.0)
                        base_z = -(text_bbox.Min.Z + text_dz / 0.9)

                        move_to_origin = rg.Transform.Translation(base_x, base_y, base_z)
                        text_3d.Transform(move_to_origin)

                        local_transform = rg.Transform.Identity

                        # === MODIFICA PERFETTO CENTRAMENTO ===
                        # Impostiamo l'altezza Z del testo esattamente su dz / 2.0. 
                        # In questo modo, l'asse mediano orizzontale della scritta combacerà 
                        # al millimetro con il centro geometrico del fianco del beam.
                        if FACCIA_DESTINAZIONE == "fianco_destro":
                            rot_side = rg.Transform.Rotation(math.radians(90), rg.Vector3d.XAxis, rg.Point3d.Origin)
                            pos_side = rg.Transform.Translation(0, dy / 2.0, dz / 2.0)
                            local_transform = pos_side * rot_side

                        elif FACCIA_DESTINAZIONE == "fianco_sinistro":
                            rot_side = rg.Transform.Rotation(math.radians(-90), rg.Vector3d.XAxis, rg.Point3d.Origin)
                            pos_side = rg.Transform.Translation(0, -dy / 2.0, dz / 2.0)
                            local_transform = pos_side * rot_side

                        elif FACCIA_DESTINAZIONE == "inferiore":
                            rot_side = rg.Transform.Rotation(math.radians(180), rg.Vector3d.XAxis, rg.Point3d.Origin)
                            pos_side = rg.Transform.Translation(0, 0, 0)
                            local_transform = pos_side * rot_side

                        else:  # "superiore"
                            rot_flip = rg.Transform.Rotation(math.radians(180), rg.Vector3d.ZAxis, rg.Point3d.Origin)
                            pos_top = rg.Transform.Translation(0,0, dz)
                            local_transform = pos_top * rot_flip

                        text_3d.Transform(local_transform)
                        text_3d.Transform(rot90)  # stessa rotazione del beam

                    if text_2d:
                        text_2d_processed = []
                        for crv in text_2d:
                            crv_copy = crv.Duplicate()
                            crv_copy.Transform(move_to_origin)
                            crv_copy.Transform(local_transform)
                            crv_copy.Transform(rot90)  # stessa rotazione del beam
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
    """Packs 2D items onto fixed-size plates using a Shelf Algorithm (First Fit)."""
    sorted_items = sorted(print_items, key=lambda x: x.length, reverse=True)
    plates = {}
    current_plate_idx = 0
    current_x = spacing
    current_y = spacing
    current_shelf_height = 0.0
    plates[0] = []

    for item in sorted_items:
        w = item.width
        l = item.length

        if current_x + w + spacing > plate_width:
            current_y += current_shelf_height + spacing
            current_x = spacing
            current_shelf_height = 0.0

        if current_y + l + spacing > plate_length:
            current_plate_idx += 1
            plates[current_plate_idx] = []
            current_x = spacing
            current_y = spacing
            current_shelf_height = 0

        target_x = current_x + w / 2
        target_y = current_y + l / 2

        # === CORREZIONE ALTEZZA Z ESPLICIATA ===
        # Estraiamo il Bounding Box reale del pezzo Rhino per capire dove si trova la sua base Z.
        z_offset = 0.0
        if item.final_rh_geo:
            bbox = item.final_rh_geo.GetBoundingBox(True)
            # bbox.Min.Z ci dice di quanti millimetri il pezzo è sopraelevato (o sotto) rispetto a Z=0
            z_offset = bbox.Min.Z

        # Applichiamo una correzione negativa (-z_offset) per costringere la base a toccare Z=0.
        placement_xform = Translation.from_vector([target_x, target_y, -z_offset])
        
        plates[current_plate_idx].append({"item": item, "pose": placement_xform})

        current_x += w + spacing
        current_shelf_height = max(current_shelf_height, l)

    return plates


# ==============================================================================
# 3. Visualization & Stats Module
# ==============================================================================

def visualize_print_setup(packed_plates, plate_width, plate_length, plate_dist=0.5):
    """Creates Rhino-compatible geometry for the packing."""
    visual_meshes = []
    visual_curves = []
    visual_texts = []
    visual_3d_texts = []
    visual_2d_text_curves = []

    for p_idx, placed_items in packed_plates.items():
        plate_origin_x = p_idx * (plate_width + plate_dist)
        plate_offset = Translation.from_vector([plate_origin_x, 0, 0])

        pt0 = Point(0, 0, 0)
        pt1 = Point(plate_width, 0, 0)
        pt2 = Point(plate_width, plate_length, 0)
        pt3 = Point(0, plate_length, 0)

        boundary_pts = [pt.transformed(plate_offset) for pt in [pt0, pt1, pt2, pt3, pt0]]
        rh_pts = [rg.Point3d(p.x, p.y, p.z) for p in boundary_pts]
        visual_curves.append(rg.Polyline(rh_pts).ToNurbsCurve())

        label_pt = boundary_pts[3]
        visual_texts.append((f"Plate {p_idx + 1}", rg.Point3d(label_pt.x, label_pt.y, label_pt.z)))

        for entry in placed_items:
            item = entry["item"]
            pose = entry["pose"]
            layout_xform = plate_offset * pose

            m = layout_xform.matrix
            rh_layout_xform = rg.Transform.Identity
            for r in range(4):
                for c in range(4):
                    rh_layout_xform[r, c] = float(m[r][c])

            if item.final_rh_geo:
                layout_mesh = item.final_rh_geo.Duplicate()
                layout_mesh.Transform(rh_layout_xform)
                visual_meshes.append(layout_mesh)

            if item.text_3d_geo:
                layout_3d_text = item.text_3d_geo.Duplicate()
                layout_3d_text.Transform(rh_layout_xform)
                visual_3d_texts.append(layout_3d_text)

            if item.text_2d_geo:
                for crv in item.text_2d_geo:
                    layout_2d_crv = crv.Duplicate()
                    layout_2d_crv.Transform(rh_layout_xform)
                    visual_2d_text_curves.append(layout_2d_crv)

            center = Point(0, 0, 0).transformed(plate_offset * pose)
            label_pos = rg.Point3d(center.x, center.y, center.z)
            visual_texts.append((item.name, label_pos))

    return visual_meshes, visual_curves, visual_texts, visual_3d_texts, visual_2d_text_curves


def visualize_in_place(print_items):
    """Returns the original unscaled/unarranged geometries and their corresponding labels."""
    in_place_meshes = []
    in_place_texts = []
    in_place_3d_texts = []
    in_place_2d_text_curves = []

    for item in print_items:
        try:
            inv_xform_compas = item.base_transformation.inverted()
            m = inv_xform_compas.matrix
            inv_rh_xform = rg.Transform.Identity
            for r in range(4):
                for c in range(4):
                    inv_rh_xform[r, c] = float(m[r][c])

            orig_geo = item.original_beam.geometry
            rh_orig_geo = None
            if hasattr(orig_geo, "to_rhino"):
                rh_orig_geo = orig_geo.to_rhino()
            elif hasattr(orig_geo, "to_brep"):
                rh_orig_geo = orig_geo.to_brep().to_rhino()
            elif type(orig_geo).__name__.endswith("RhinoBrep"):
                rh_orig_geo = getattr(orig_geo, "brep", getattr(orig_geo, "native_brep", getattr(orig_geo, "_brep", None)))
            else:
                try:
                    rh_orig_geo = orig_geo.to_mesh().to_rhino()
                except:
                    pass

            if rh_orig_geo:
                in_place_meshes.append(rh_orig_geo)
            else:
                if item.final_rh_geo:
                    geo_back = item.final_rh_geo.Duplicate()
                    geo_back.Transform(inv_rh_xform)
                    in_place_meshes.append(geo_back)

            # === VISUALIZZAZIONE IN PLACE DEI TESTI ===
            if item.final_rh_geo:
                bbox_now = item.final_rh_geo.GetBoundingBox(True)
                cx = (bbox_now.Max.X + bbox_now.Min.X) / 2.0
                cy = (bbox_now.Max.Y + bbox_now.Min.Y) / 2.0
                cz = (bbox_now.Max.Z + bbox_now.Min.Z) / 2.0
                inv_rot90 = rg.Transform.Rotation(
                    math.radians(-90),
                    rg.Vector3d.XAxis,
                    rg.Point3d(cx, cy, cz)
                )

                if item.text_3d_geo:
                    text_3d_back = item.text_3d_geo.Duplicate()
                    text_3d_back.Transform(inv_rot90)
                    text_3d_back.Transform(inv_rh_xform)
                    in_place_3d_texts.append(text_3d_back)

                if item.text_2d_geo:
                    for crv in item.text_2d_geo:
                        crv_back = crv.Duplicate()
                        crv_back.Transform(inv_rot90)
                        crv_back.Transform(inv_rh_xform)
                        in_place_2d_text_curves.append(crv_back)

            pt = Point(0, 0, 0).transformed(inv_xform_compas)
            in_place_texts.append((item.name, rg.Point3d(pt.x, pt.y, pt.z)))

        except Exception as e:
            print(f"Skipped in-place visualization for {item.name}: {e}")

    return in_place_meshes, in_place_texts, in_place_3d_texts, in_place_2d_text_curves


def get_print_stats(packed_plates, duration_per_mm3=0.01, cost_per_mm3=0.005):
    """Calculates stats based on packed items."""
    total_volume = 0.0
    total_items = 0
    plate_count = len(packed_plates)

    for p_idx, items in packed_plates.items():
        for entry in items:
            total_items += 1
            total_volume += entry["item"].volume

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


def convert_compas_to_rhino_mesh(compas_geo):
    try:
        if hasattr(compas_geo, "to_rhino"):
            return compas_geo.to_rhino()
    except:
        pass
    return None
