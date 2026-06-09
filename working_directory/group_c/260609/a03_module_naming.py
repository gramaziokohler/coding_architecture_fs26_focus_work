import Rhino.Geometry as rg
import math

# No longer needed: 3D text generation is replaced by COMPAS Timber's Text feature

def run_module_naming(timber_model, TextHeight=0.03):
    """
    Uses COMPAS Timber's Text feature for engraving beams with module+number identifiers.
    Beams must already have module and number attributes from run_numbering().
    
    Returns:
    - [0] named_labels: list of beam names used for engraving
    - [1] ordered_beams: list of beams with Text features added
    - [2] engraving_refs: reference info for each engraving (ref_side_index, etc.)
    - [3] report_string: summary report of engraving operations
    - [4] timber_model: updated model with Text features attached to beams
    """
    from compas_timber.fabrication import Text, AlignmentType
    
    named_labels = []
    ordered_beams = []
    engraving_refs = []
    summary_report = []
    
    summary_report.append("=== REPORT: STRUCTURAL UNIFIED NOMENCLATURE ===")
    t_height = float(TextHeight) if TextHeight else 0.03
    
    if not timber_model:
        return [], [], [], "Error: timber_model not connected."
    
    def select_engraving_ref_side(beam):
        """Select ref side with most features; default to 2 (top) if none."""
        counts = {}
        for f in beam.features:
            counts[f.ref_side_index] = counts.get(f.ref_side_index, 0) + 1
        
        if not counts:
            return 2  # Default to top face
        
        return max(counts, key=lambda index: (counts[index], -index))
    
    # Process each beam using its stored partitioning attributes
    for beam in timber_model.beams:
        # Get beam name from attributes (set by run_numbering)
        beam_name = beam.attributes.get('display_name', None)
        
        if not beam_name:
            # Fallback: construct from module + number if display_name not set
            module = beam.attributes.get('module')
            number = beam.attributes.get('number')
            if module and number:
                beam_name = f"{module}{number}"
            else:
                summary_report.append(f" -> Beam {beam.key}: No module/number attributes, skipping")
                continue
        
        try:
            # Select which ref side to engrave on
            ref_side_index = select_engraving_ref_side(beam)
            side_surface = beam.side_as_surface(ref_side_index)
            
            # Use user-provided text height (COMPAS Timber's Text feature handles sizing)
            text_height = t_height
            
            # Create Text feature centered on the surface
            text_feature = Text(
                ref_side_index=ref_side_index,
                start_x=side_surface.xsize / 2.0,
                start_y=side_surface.ysize / 2.0,
                alignment_horizontal=AlignmentType.CENTER,
                alignment_vertical=AlignmentType.CENTER,
                text_height=text_height,
                text=beam_name,
            )
            
            beam.add_features([text_feature])
            
            # Store engraving position as attributes for downstream packing
            beam.attributes["engraving_ref_side"] = ref_side_index
            beam.attributes["engraving_start_x"] = side_surface.xsize / 2.0
            beam.attributes["engraving_start_y"] = side_surface.ysize / 2.0
            beam.attributes["text_height"] = text_height
            
            named_labels.append(beam_name)
            ordered_beams.append(beam)
            engraving_refs.append({
                "beam_name": beam_name,
                "ref_side_index": ref_side_index,
                "start_x": side_surface.xsize / 2.0,
                "start_y": side_surface.ysize / 2.0,
                "text_height": text_height,
            })
            
            summary_report.append(f" -> Beam {beam_name}: Text feature added on ref side {ref_side_index}")
            
        except Exception as e:
            summary_report.append(f" -> Beam {beam_name}: Error - {str(e)}")
    
    report_string = "\n".join(summary_report)
    
    return (
        named_labels,
        ordered_beams,
        engraving_refs,
        report_string,
        timber_model
    )
