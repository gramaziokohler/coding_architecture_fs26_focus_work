import Rhino.Geometry as rg
import Rhino
import System

def create_oriented_text_curves(text, base_plane, text_height=6.0):
    try:
        te = rg.TextEntity()
        te.Text = text
        te.Plane = rg.Plane.WorldXY
        te.FontIndex = 0
        te.TextHeight = text_height

        curves = te.Explode()
        if not curves:
            return []

        joined_curves = rg.Curve.JoinCurves(curves, 0.001) or []
        
        bbox = rg.PolylineCurve([rg.Point3d(0,0,0)]).GetBoundingBox(True)
        if joined_curves:
            joined_all = rg.Curve.JoinCurves(joined_curves, 0.1)
            if joined_all:
                bbox = joined_all[0].GetBoundingBox(True)
            else:
                bbox = joined_curves[0].GetBoundingBox(True)
                
        text_dx = bbox.Max.X - bbox.Min.X
        text_dy = bbox.Max.Y - bbox.Min.Y
        
        center_xform = rg.Transform.Translation(-(bbox.Min.X + text_dx/2.0), -(bbox.Min.Y + text_dy/2.0), 0)
        orient_xform = rg.Transform.PlaneToPlane(rg.Plane.WorldXY, base_plane)
        
        final_xform = orient_xform * center_xform
        
        oriented_curves = []
        for crv in joined_curves:
            c = crv.DuplicateCurve()
            c.Transform(final_xform)
            oriented_curves.append(c)
            
        return oriented_curves
    except:
        return []

def run_module_naming(A_beams, B_beams, C_beams, D_beams, E_beams, F_beams, TextHeight=6.0):
    """
    Riconosce i Guid, stringhe o geometrie passate dai componenti precedenti,
    estrae i solidi nativi in modo difensivo e genera le curve di testo orientate.
    """
    modules_input = {
        "A": A_beams if isinstance(A_beams, list) else ([A_beams] if A_beams is not None else []),
        "B": B_beams if isinstance(B_beams, list) else ([B_beams] if B_beams is not None else []),
        "C": C_beams if isinstance(C_beams, list) else ([C_beams] if C_beams is not None else []),
        "D": D_beams if isinstance(D_beams, list) else ([D_beams] if D_beams is not None else []),
        "E": E_beams if isinstance(E_beams, list) else ([E_beams] if E_beams is not None else []),
        "F": F_beams if isinstance(F_beams, list) else ([F_beams] if F_beams is not None else [])
    }
    
    all_named_labels = []      
    all_beam_geometries = []   
    all_text_curves = []  
    summary_report = []        
    
    summary_report.append("=== REPORT SEQUENZA COSTRUTTIVA MODULI ===")
    t_height = float(TextHeight) if TextHeight else 6.0
    doc = Rhino.RhinoDoc.ActiveDoc
    
    for letter in sorted(modules_input.keys()):
        beams = modules_input[letter]
        clean_beams = [b for b in beams if b is not None]
        summary_report.append("\nModulo {}: {} elementi trovati".format(letter, len(clean_beams)))
        
        for index, item in enumerate(clean_beams):
            sequence_number = index + 1
            label = "{}{}".format(letter, sequence_number)
            
            # --- PROTEZIONE OPZIONE B: CONVERSIONE DIFENSIVA DEL DATO ---
            rhino_geom = None
            
            # 1. Se è già una geometria nativa di Rhino passata direttamente (Brep, Mesh, Extrusion)
            if hasattr(item, "GetBoundingBox"):
                rhino_geom = item
            
            # 2. Se è un Guid o una stringa, andiamo a cercarlo nel database attivo di Rhino
            else:
                try:
                    item_str = str(item)
                    # Verifica standard se la stringa somiglia a un Guid valido
                    if len(item_str) == 36 and item_str.count('-') == 4:
                        g_id = System.Guid(item_str)
                        rh_obj = doc.Objects.FindId(g_id)
                        if rh_obj:
                            rhino_geom = rh_obj.Geometry
                except:
                    pass
            
            # 3. Fallback nel caso in cui sia rimasto un oggetto wrapper di COMPAS Timber
            if rhino_geom is None and hasattr(item, "geometry"):
                try:
                    if hasattr(item.geometry, "native_brep") and item.geometry.native_brep:
                        rhino_geom = item.geometry.native_brep
                    elif hasattr(item.geometry, "to_rhino"):
                        rhino_geom = item.geometry.to_rhino()
                except:
                    pass

            # Se l'elemento è completamente vuoto o non convertibile, non blocchiamo l'intero ciclo
            if rhino_geom is None:
                summary_report.append(" -> Pezzo {} NON convertito (Tipo non supportato: {})".format(label, type(item).__name__))
                continue
            
            # Se siamo qui la geometria è valida, la aggiungiamo agli elenchi di output
            all_named_labels.append(label)
            all_beam_geometries.append(rhino_geom)
            
            # --- CALCOLO DEL PIANO LOCALE ORIENTATO ---
            plane_found = False
            local_plane = rg.Plane.WorldXY
            
            try:
                bbox = rhino_geom.GetBoundingBox(True)
                center_point = bbox.Center
                
                if hasattr(rhino_geom, "Faces"):
                    best_face = None
                    max_z = -1.0
                    for face in rhino_geom.Faces:
                        _, u, v = face.ClosestPoint(center_point)
                        normal = face.NormalAt(u, v)
                        if normal.Z > max_z:
                            max_z = normal.Z
                            best_face = face
                    
                    if best_face:
                        _, u, v = best_face.ClosestPoint(center_point)
                        _, local_plane = best_face.FrameAt(u, v)
                        local_plane.Translate(local_plane.Normal * 1.0) # Spostamento minimo anti-flickering
                        plane_found = True
            except:
                pass
                
            if not plane_found:
                bbox = rhino_geom.GetBoundingBox(True)
                local_plane = rg.Plane(bbox.Center, rg.Vector3d.ZAxis)
                local_plane.Translate(rg.Vector3d.ZAxis * (bbox.Max.Z - bbox.Center.Z + 1.0))
            
            # Generazione delle curve di testo tridimensionali orientate
            curves_list = create_oriented_text_curves(label, local_plane, text_height=t_height)
            all_text_curves.extend(curves_list)
            
            summary_report.append(" -> Posizione {}: ID {}".format(sequence_number, label))
            
    report_string = "\n".join(summary_report)
    
    return (
        all_named_labels,      
        all_beam_geometries,   
        all_text_curves,       
        report_string          
    )