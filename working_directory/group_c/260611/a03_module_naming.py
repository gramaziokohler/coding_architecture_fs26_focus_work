# venv: ca-fs26-final-project
# keyword: timber-module, module-naming-update, attribute-sync
import Rhino.Geometry as rg
import math

def create_3d_text_engraving_inplace(text, text_height=0.03, engraving_depth=0.005):
    """
    Genera il testo come solido 3D (Brep) perfettamente centrato sul baricentro XYZ
    nell'origine WorldXY, scalato in metri per evitare i limiti di precisione di Rhino.
    """
    try:
        scale_factor = 1000.0
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
            return None, 0.0, 0.0

        joined_curves = rg.Curve.JoinCurves(curves, fine_tol) or []
        text_breps = rg.Brep.CreatePlanarBreps(joined_curves, fine_tol)
        if not text_breps:
            return None, 0.0, 0.0

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
        if not final_3d:
            return None, 0.0, 0.0

        text_bbox = final_3d.GetBoundingBox(True)
        cx = (text_bbox.Max.X + text_bbox.Min.X) / 2.0
        cy = (text_bbox.Max.Y + text_bbox.Min.Y) / 2.0
        cz = text_bbox.Max.Z 
        
        move_to_center = rg.Transform.Translation(-cx, -cy, -cz)
        final_3d.Transform(move_to_center)

        downscale = rg.Transform.Scale(rg.Plane.WorldXY, 1.0/scale_factor, 1.0/scale_factor, 1.0/scale_factor)
        final_3d.Transform(downscale)

        real_width = (text_bbox.Max.X - text_bbox.Min.X) / scale_factor
        real_height = (text_bbox.Max.Y - text_bbox.Min.Y) / scale_factor
        return final_3d, real_width, real_height
    except:
        return None, 0.0, 0.0


def run_module_naming(timber_model, TextHeight=0.03):
    """
    Sincronizza i dati estratti dagli attributi di partizione del componente precedente
    e genera le marcature 3D solide in-place basate sulla sequenza reale dei moduli.
    """
    all_named_labels = []      
    all_beam_geometries = []   
    all_text_solids = []  
    summary_report = []        
    
    summary_report.append("=== REPORT STRUTTURALE NOMENCLATURA SINCRONIZZATA ===")
    t_height = float(TextHeight) if TextHeight else 0.03
    engrave_depth = 0.005 
    
    if not timber_model:
        return [], [], [], "Errore: timber_model non collegato.", None

    for i, beam in enumerate(timber_model.beams):
        
        # === STRATEGIA DI COERENZA SINCRO: LETTURA ATTRIBUTI NATIVI DI NUMBER_BEAMS ===
        module_letter = None
        sequence_number = None
        
        # Estraiamo il dizionario degli attributi interni memorizzato da set_beam_partitioning_attributes
        attributes = getattr(beam, "attributes", {}) or {}
        
        if isinstance(attributes, dict):
            module_letter = attributes.get("module")
            sequence_number = attributes.get("number") or attributes.get("beam_number")
            
        # Fallback di sicurezza estremo se per qualche motivo gli attributi si sono svuotati nella cache
        if not module_letter or sequence_number is None:
            old_name = getattr(beam, 'name', None) or getattr(beam, 'id', '')
            old_name_str = str(old_name).strip().upper()
            if old_name_str and not old_name_str.isdigit():
                module_letter = old_name_str[0]
                # Estrae i numeri finali dalla stringa precedente
                num_parts = "".join([c for c in old_name_str if c.isdigit()])
                sequence_number = int(num_parts) if num_parts else (i + 1)
            else:
                module_letter = "M"
                sequence_number = i + 1

        # Componiamo la stringa pulita secondo le tue specifiche (Lettera Modulo + Sequenza di Costruzione)
        beam_name = "{}{}".format(str(module_letter).upper(), int(sequence_number))
        
        # Sincronizziamo anche la proprietà nativa del beam per passarla ai moduli successivi di Nesting
        beam.name = beam_name
            
        # Estrazione della geometria nativa di Rhino memorizzata in COMPAS
        rh_geo = None
        geo = beam.geometry
        if hasattr(geo, "to_rhino"):
            rh_geo = geo.to_rhino()
        elif hasattr(geo, "to_brep"):
            rh_geo = geo.to_brep().to_rhino()
        elif type(geo).__name__.endswith("RhinoBrep"):
            rh_geo = getattr(geo, "brep", getattr(geo, "native_brep", getattr(geo, "_brep", None)))
            
        if not rh_geo:
            continue

        all_named_labels.append(beam_name)
        all_beam_geometries.append(rh_geo)
        
        try:
            solid_text, t_width, t_height_box = create_3d_text_engraving_inplace(beam_name, text_height=t_height, engraving_depth=engrave_depth)
            if not solid_text:
                continue
            
            c_origin = beam.frame.point
            c_xaxis = beam.frame.xaxis
            c_yaxis = beam.frame.yaxis
            c_zaxis = beam.frame.zaxis
            
            rh_origin = rg.Point3d(c_origin.x, c_origin.y, c_origin.z)
            rh_xaxis = rg.Vector3d(c_xaxis.x, c_xaxis.y, c_xaxis.z)
            rh_yaxis = rg.Vector3d(c_yaxis.x, c_yaxis.y, c_yaxis.z)
            rh_zaxis = rg.Vector3d(c_zaxis.x, c_zaxis.y, c_zaxis.z)
            
            if rh_zaxis.Z < 0:
                rh_zaxis = -rh_zaxis
                rh_yaxis = -rh_yaxis

            beam_plane = rg.Plane(rh_origin, rh_xaxis, rh_yaxis)
            
            h_offset = 0.0
            for h_attr in ['height', 'h', 'd', 'depth']:
                if hasattr(beam, h_attr):
                    h_offset = float(getattr(beam, h_attr))
                    break
            
            if h_offset > 0:
                beam_plane.Translate(rh_zaxis * (h_offset / 2.0))
            else:
                bbox = rh_geo.GetBoundingBox(True)
                beam_plane.Translate(rh_zaxis * (bbox.Max.Z - rh_origin.Z))

            try: beam_length = beam.centerline.length
            except: beam_length = 1.0

            beam_plane.Translate(beam_plane.XAxis * (beam_length / 2.0))
            
            step = 0.02  
            max_shift = (beam_length / 2.0) - 0.10  
            current_shift = 0.0
            
            scan_plane = rg.Plane(beam_plane)
            
            while current_shift < max_shift:
                test_points = [
                    scan_plane.Origin,
                    scan_plane.Origin - (scan_plane.XAxis * (t_width / 2.0)) - (scan_plane.YAxis * (t_height_box / 2.0)),
                    scan_plane.Origin + (scan_plane.XAxis * (t_width / 2.0)) - (scan_plane.YAxis * (t_height_box / 2.0)),
                    scan_plane.Origin - (scan_plane.XAxis * (t_width / 2.0)) + (scan_plane.YAxis * (t_height_box / 2.0)),
                    scan_plane.Origin + (scan_plane.XAxis * (t_width / 2.0)) + (scan_plane.YAxis * (t_height_box / 2.0))
                ]
                
                area_is_fully_solid = True
                
                for pt in test_points:
                    ray_start = pt + (scan_plane.Normal * 0.01)
                    ray_end = pt - (scan_plane.Normal * 0.01)
                    ray_line = rg.Line(ray_start, ray_end).ToNurbsCurve()
                    
                    intersections = rg.Intersect.Intersection.CurveBrep(ray_line, rh_geo, 0.001)
                    
                    point_hits_solid_wood = False
                    if intersections and len(intersections[2]) > 0:
                        highest_pt = min(intersections[2], key=lambda p: p.DistanceTo(pt))
                        if highest_pt.DistanceTo(pt) < 0.006:
                            point_hits_solid_wood = True
                            
                    if not point_hits_solid_wood:
                        area_is_fully_solid = False
                        break
                
                if area_is_fully_solid:
                    break  
                
                scan_plane.Translate(scan_plane.XAxis * step)
                current_shift += step

            beam_plane = rg.Plane(scan_plane)

            beam_plane.XAxis = -beam_plane.XAxis
            beam_plane.YAxis = -beam_plane.YAxis
            
            plane_to_plane_xform = rg.Transform.PlaneToPlane(rg.Plane.WorldXY, beam_plane)
            
            oriented_solid = solid_text.DuplicateBrep()
            oriented_solid.Transform(plane_to_plane_xform)
            
            oriented_solid.Transform(rg.Transform.Translation(-rh_zaxis * engrave_depth))
            
            all_text_solids.append(oriented_solid)
            summary_report.append(" -> Sincronizzato {}: (Shift: {:.2f}m)".format(beam_name, current_shift))
        except Exception as e:
            summary_report.append(" -> Errore trave {}: {}".format(beam_name, e))
            
    report_string = "\n".join(summary_report)
    
    return (
        all_named_labels,      
        all_beam_geometries,   
        all_text_solids,       
        report_string,
        timber_model          
    )