from compas_timber.model import TimberModel 
from compas_timber.structural import StructuralGraph

import Rhino
import Rhino.Geometry as rg

TOLERANCE = 0.05
Z_SUPPORT_TOL = 0.1

# --------------------------------------------------
# --- Structural Model Processing ------------------
# --------------------------------------------------

def process_structural_model(model):
    """
    Processes a timber model into structural segments, nodes, and virtual elements.
    Utilizes StructuralGraph from compas_timber (v2.1.1+).
    """    
    if not any(model.get_beam_structural_segments(beam) for beam in model.beams):
        model.create_beam_structural_segments()

    # 2. Create the Structural Graph
    sg = StructuralGraph.from_model(model)
    
    # 3. Extract Nodes & Supports
    nodes_data = [] # List of (pt, is_support, index)
    for node_key in sg.nodes():
        idx = sg.node_index(node_key)
        pt = sg.node_point(node_key)
        is_support = abs(pt.z) <= Z_SUPPORT_TOL
        nodes_data.append({"point": pt, "is_support": is_support, "index": idx})

    # 4. Extract Elements (grouped by beam)
    beam_elements = []
    for b_idx, beam in enumerate(model.beams):
        edges = sg.segments_for_beam(beam)
        if not edges:
            continue
            
        segments = []
        for s_idx, (u, v) in enumerate(edges):
            seg = sg.segment(u, v)
            
            # Cross section logic
            if seg.cross_section:
                w, h = seg.cross_section
            else:
                w, h = beam.width, beam.height
            
            segments.append({
                "line": seg.line,
                "frame": seg.frame,
                "width": w,
                "height": h,
                "node_indices": (sg.node_index(u), sg.node_index(v)),
                "id": "B{}_S{}".format(b_idx, s_idx)
            })
        beam_elements.append(segments)

    # 5. Extract Virtual Elements
    virtual_elements = []
    for c_idx, (u, v) in enumerate(sg.connector_edges):
        seg = sg.segment(u, v)
        virtual_elements.append({
            "line": seg.line,
            "node_indices": (sg.node_index(u), sg.node_index(v)),
            "id": "V_{}".format(c_idx)
        })

    return {
        "nodes": nodes_data,
        "beams": beam_elements,
        "virtual": virtual_elements
    }


def create_analysis_report(model, total_weight, loadcase_names, max_displacements, utilisations_tree):
    """
    Erstellt einen formatierten Report.
    
    Args:
        model: Das TimberModel.
        total_weight: Gesamtgewicht (float).
        loadcase_names: Liste von Strings (z.B. ["LC1: Dead", "LC2: Snow", "LC3: Wind"]).
        max_displacements: Liste mit einem Max-Wert pro Lastfall (z.B. [0.012, 0.045, 0.008] in m).
        utilisations_tree: GH DataTree mit einer Branch pro Lastfall, darin alle Member-Werte.
    """
    total_length = sum(beam.length for beam in model.beams)
    beam_count = len(list(model.beams))
    
    report = []
    report.append("|| STRUCTURAL ANALYSIS REPORT ||")
    report.append("=" * 44)
    report.append("MODEL INFO")
    report.append("Total Beam Length: {:.1f} m".format(total_length))
    report.append("Beam Count:        {}".format(beam_count))
    report.append("Total Weight:      {:.1f} kg".format(total_weight))
    
    # Durch die Lastfälle iterieren
    for i, name in enumerate(loadcase_names):
        report.append("-" * 44)
        report.append("LOADCASE: {}".format(name.upper()))
        
        # 1. Verschiebung (direkt aus der Liste der Max-Werte)
        m_disp = max_displacements[i] if i < len(max_displacements) else 0.0
        report.append("Max. Displacement: {:.3f} cm".format(m_disp))
        
        # 2. Ausnutzung (Durchschnitt und Max aus dem DataTree berechnen)
        if i < utilisations_tree.BranchCount:
            branch_values = utilisations_tree.Branch(i)
            if branch_values:
                m_util = max(branch_values)
                a_util = sum(branch_values) / len(branch_values)
                report.append("Max. Utilisation:  {:.2f} %".format(m_util * 100))
                report.append("Avg. Utilisation:  {:.2f} %".format(a_util * 100))
            else:
                report.append("Utilisation:       No data")
        else:
            report.append("Utilisation:       No data for LC")

    report.append("=" * 44)
    return "\n".join(report)

def create_preview(text, pt, size, plane):
    te = rg.TextEntity()
    te.Text = text
    te.Plane = plane
    te.TextHeight = size
    
    font_idx = Rhino.RhinoDoc.ActiveDoc.Fonts.FindOrCreate("Consolas", False, False)
    if font_idx != -1: te.FontIndex = font_idx
    
    te.Justification = Rhino.Geometry.TextJustification.BottomLeft
    return te

def calculate_wind_loads(model, wind_angle_deg, q_wind=0.56, c_shape=1.2, safety_factor= 1.35):
    """
    Berechnet Windlast-Vektoren für alle Segmente des Struktur-Graphen.
    Versöhnt die 84 Haupt-Beams mit den 304 Karamba-Elementen.
    """
    from compas.geometry import Vector
    from compas_timber.structural import StructuralGraph
    import math
    
    # 1. Wind-Vektor vorbereiten
    rad = math.radians(wind_angle_deg)
    wind_dir = Vector(math.cos(rad), math.sin(rad), 0.0)
    
    # 2. Struktur-Graph (die 304 Segmente)
    if not any(model.get_beam_structural_segments(beam) for beam in model.beams):
        model.create_beam_structural_segments()
    
    sg = StructuralGraph.from_model(model)
    
    results = [] # Liste von Dictionaries: {"id": "B0_S0", "vector": [x,y,z]}
    
    # 3. Über alle Beams und deren Segmente iterieren
    for b_idx, beam in enumerate(model.beams):
        # Basis-Info vom Hauptbalken (Querschnitt & Orientierung)
        f = beam.frame
        v_y, v_z = f.yaxis, f.zaxis
        
        # f.yaxis, f.zaxis 
        dot_y = abs(wind_dir.dot(v_y))
        dot_z = abs(wind_dir.dot(v_z))
        
        b_eff = (beam.width * dot_y + beam.height * dot_z)
        
        
        # Lastbetrag (kN/m)
        load_mag = q_wind * c_shape * b_eff * safety_factor
        lv = wind_dir * load_mag
        
        # Segmente dieses Balkens im Graphen finden
        edges = sg.segments_for_beam(beam)
        for s_idx, (u, v) in enumerate(edges):     
            seg_id = "B{}_S{}".format(b_idx, s_idx)
            results.append({
                "id": seg_id,
                "vector": [lv.x, lv.y, lv.z]
            })
            
    return results


def calculate_wind_loads_sia(model, wind_angle_deg, qp0=0.9, terrain_category="III", z_max=3.0, c_force=2.0, gamma_q=1.35):
    """
    Berechnet Windlast-Vektoren als Linienlasten [kN/m] für alle Segmente
    des Struktur-Graphen eines COMPAS Timber Modells.

    Annahmen:
    - SIA 261-Logik mit qp = ch * qp0
    - qp wird am höchsten Punkt des Bauwerks bestimmt und über die Höhe konstant angesetzt
    - Rechteckquerschnitte werden konservativ mit konstantem Kraftbeiwert c_force behandelt
    - Sicherheitsbeiwert gamma_q wird direkt hier integriert, weil Karamba später nicht mehr anpasst
    """
    import math
    from compas.geometry import Vector
    from compas_timber.structural import StructuralGraph

    def _terrain_parameters(category):
        """
        SIA 261 Tabelle 4:
        Geländekategorie -> (zg, alpha_r, z_min)
        """
        table = {
            "II":  (300.0, 0.16, 5.0),
            "IIA": (380.0, 0.19, 5.0),
            "III": (450.0, 0.23, 5.0),
            "IV":  (526.0, 0.30, 10.0),
        }
        key = str(category).upper()
        if key not in table:
            raise ValueError(
                "terrain_category must be one of: 'II', 'IIa', 'III', 'IV'"
            )
        return table[key]

    def _profile_factor_ch(category, z):
        """
        SIA 261 Gl. (12), in üblicher Lesart:
            ch = 1.6 * ((z / zg) ** alpha_r + 0.375) ** 2

        Für kleine Höhen gilt gemäss SIA:
        - II, IIa, III: z >= 5 m
        - IV: z >= 10 m
        """
        zg, alpha_r, z_min = _terrain_parameters(category)
        z_ref = max(float(z), z_min)
        ch = 1.6 * (((z_ref / zg) ** alpha_r) + 0.375) ** 2
        return ch, z_ref

    # Windrichtung in XY
    rad = math.radians(wind_angle_deg)
    wind_dir = Vector(math.cos(rad), math.sin(rad), 0.0)

    # SIA: qp am höchsten Punkt bestimmen
    ch, z_ref = _profile_factor_ch(terrain_category, z_max)
    qp_char = ch * qp0              # charakteristischer Staudruck [kN/m²]
    qp_design = qp_char * gamma_q   # Bemessungswert direkt hier integriert

    # Sicherstellen, dass Segmente existieren
    if not any(model.get_beam_structural_segments(beam) for beam in model.beams):
        model.create_beam_structural_segments()

    sg = StructuralGraph.from_model(model)

    results = []

    for b_idx, beam in enumerate(model.beams):
        f = beam.frame
        v_y = f.yaxis
        v_z = f.zaxis

        # Effektive projizierte Breite pro Meter Stablänge
        # für Rechteckquerschnitt bei horizontalem Wind
        dot_y = abs(wind_dir.dot(v_y))
        dot_z = abs(wind_dir.dot(v_z))
        b_eff = beam.width * dot_y + beam.height * dot_z

        # Linienlast [kN/m]
        # q = qp_design * c_force * b_eff
        load_mag = qp_design * c_force * b_eff

        # Lastvektor in Windrichtung
        lv = wind_dir * load_mag

        edges = sg.segments_for_beam(beam)
        for s_idx, (u, v) in enumerate(edges):
            seg_id = "B{}_S{}".format(b_idx, s_idx)
            results.append({
                "id": seg_id,
                "vector": [lv.x, lv.y, lv.z],
                "meta": {
                    "qp_char": qp_char,
                    "qp_design": qp_design,
                    "ch": ch,
                    "z_ref": z_ref,
                    "b_eff": b_eff,
                    "load_mag": load_mag,
                    "c_force": c_force,
                    "gamma_q": gamma_q,
                }
            })

    return results
