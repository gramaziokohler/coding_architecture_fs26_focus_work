import Rhino.Geometry as rg

def run_module_naming(A_beams, B_beams, C_beams, D_beams, E_beams, F_beams):
    """
    Prende i pacchetti di travi divisi per modulo e applica la nomenclatura
    strutturata (LetteraModulo + NumeroSequenza).
    """
    # Dizionario di mappatura input
    modules_input = {
        "A": A_beams or [],
        "B": B_beams or [],
        "C": C_beams or [],
        "D": D_beams or [],
        "E": E_beams or [],
        "F": F_beams or []
    }
    
    # Liste di output per Grasshopper
    all_named_labels = []      # Lista flat di stringhe ("A1", "A2", ...)
    all_beam_geometries = []   # Lista flat di geometrie corrispondenti
    all_text_dots = []         # Tag 3D pronti da visualizzare in Rhino
    summary_report = []        # Report di testo per un pannello
    
    summary_report.append("=== REPORT SEQUENZA COSTRUTTIVA MODULI ===")
    
    # Scorriamo i moduli in ordine alfabetico
    for letter in sorted(modules_input.keys()):
        beams = modules_input[letter]
        summary_report.append("\nModulo {}: {} elementi trovati".format(letter, len(beams)))
        
        for index, beam in enumerate(beams):
            # Generazione del nome sequenziale (es. A1, A2, A3...)
            sequence_number = index + 1
            label = "{}{}".format(letter, sequence_number)
            
            all_named_labels.append(label)
            all_beam_geometries.append(beam)
            
            # Calcolo del punto medio della trave per posizionare il Tag di testo 3D
            try:
                # Se è una mesh/brep prendiamo il centro della Bounding Box
                bbox = beam.GetBoundingBox(True)
                center_point = bbox.Center
            except:
                # Fallback generico se l'oggetto non ha Bounding Box diretta
                center_point = rg.Point3d(0, 0, 0)
                
            all_text_dots.append(rg.TextDot(label, center_point))
            summary_report.append(" -> Posizione {}: ID {}".format(sequence_number, label))
            
    report_string = "\n".join(summary_report)
    
    # Return ordinato (Tupla 0-3)
    return (
        all_named_labels,      # 0
        all_beam_geometries,   # 1
        all_text_dots,         # 2
        report_string          # 3
    )