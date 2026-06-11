# venv: ca-fs26-focus-work
# keyword: timber-packing, production-layout, attribute-driven
import Rhino.Geometry as rg

def get_flatten_xform(beam, geom_obj=None):
    """Convert beam or blank 3D frame to 2D layout (flatten to WorldXY plane)."""
    f = getattr(geom_obj, "frame", None) or beam.frame
    plane = rg.Plane(rg.Point3d(f.point.x, f.point.y, f.point.z), 
                     rg.Vector3d(f.xaxis.x, f.xaxis.y, f.xaxis.z), 
                     rg.Vector3d(f.yaxis.x, f.yaxis.y, f.yaxis.z))
    return rg.Transform.PlaneToPlane(plane, rg.Plane.WorldXY)

def get_rhino_geometry(geom_obj):
    """Extract native Rhino geometry from COMPAS wrappers."""
    if geom_obj is None:
        return None
    # If it's already a Rhino geometry object, use it
    if hasattr(geom_obj, 'Duplicate'):
        return geom_obj
    # Extract from RhinoBrep wrapper
    if hasattr(geom_obj, 'native_brep'):
        return geom_obj.native_brep
    if hasattr(geom_obj, 'brep'):
        return geom_obj.brep
    if hasattr(geom_obj, '_brep'):
        return geom_obj._brep
    if hasattr(geom_obj, 'Geometry'):
        return geom_obj.Geometry
    return geom_obj

def duplicate_geometry(geo):
    if hasattr(geo, 'DuplicateBrep'):
        return geo.DuplicateBrep()
    if hasattr(geo, 'Duplicate'):
        return geo.Duplicate()
    return None

def get_positive_number(value):
    try:
        number = float(value)
        return number if number > 0 else None
    except:
        return None

def get_blank_length(beam, fallback=None):
    """Read the packing length from beam.blank geometry, not custom beam attributes."""
    blank = getattr(beam, "blank", None)
    for attr in ("length", "lenght", "xsize", "x_size", "size_x"):
        number = get_positive_number(getattr(blank, attr, None))
        if number:
            return number, "beam.blank.{}".format(attr)

    return fallback, "measured beam.blank bounding length fallback"

def create_geometry_text(text, position, text_height=0.03):
    """Create 2D text geometry centered at position."""
    te = rg.TextEntity()
    te.Text = text
    te.FontIndex = 0
    te.TextHeight = text_height
    plane = rg.Plane.WorldXY
    plane.Origin = position
    te.Plane = plane
    curves = te.Explode()
    if not curves:
        return []
    joined = rg.Curve.JoinCurves(curves, 0.001) or curves
    bbox = te.GetBoundingBox(True)
    if bbox.IsValid:
        cx = (bbox.Max.X + bbox.Min.X) / 2.0
        cy = (bbox.Max.Y + bbox.Min.Y) / 2.0
        move = rg.Transform.Translation(position.X - cx, position.Y - cy, 0)
        for crv in joined:
            crv.Transform(move)
    return joined

def run_packing(timber_model, origin, saw_gap, label_offset, price_lm):
    """
    Flatten and nest timber beams in 2D production layout using stored attributes.
    
    Input:
    - timber_model: TimberModel with beams containing partitioning attributes
    - origin: Point3d for layout start position
    - saw_gap: Distance between nested beams
    - label_offset: Z-height offset for label text
    - price_lm: Cost per linear meter
    
    Returns:
    - [0] arr_boxes: Flattened beam geometry in nested positions
    - [1] arr_names: Label text geometry for each beam (display_name attribute)
    - [2] arr_lines: Reference lines showing beam positions
    - [3] max_length: Maximum beam length in layout
    - [4] dims: List of individual beam lengths
    - [5] num_txt: Text labels with dimensions
    - [6] stock_info: Metadata per beam (module, number, position)
    - [7] report: Production report with cost breakdown
    """
    
    if not timber_model or not timber_model.beams:
        return [], [], [], 0, [], [], [], "Error: No beams in timber_model"
    
    # Extract beam blanks with their attributes. Packing must be based on
    # beam.blank, not on the cut beam geometry.
    processed = []
    for beam in timber_model.beams:
        blank_obj = getattr(beam, "blank", None)
        native_geo = get_rhino_geometry(blank_obj)
        if native_geo is None:
            raise ValueError("Beam {} has no usable beam.blank for packing".format(getattr(beam, "key", "?")))
        
        xform = get_flatten_xform(beam, blank_obj)
        geo = duplicate_geometry(native_geo)
        if geo is None:
            raise ValueError("Beam {} beam.blank could not be duplicated for packing".format(getattr(beam, "key", "?")))
        geo.Transform(xform)
        
        # Read display name from attributes (set by run_module_naming)
        display_name = beam.attributes.get("display_name", "?")
        module = beam.attributes.get("module", "")
        number = beam.attributes.get("number", "")
        beam_id = beam.attributes.get("beam_id", "")
        
        bbox = geo.GetBoundingBox(True)
        measured_blank_length = bbox.Max.X - bbox.Min.X
        length, length_source = get_blank_length(beam, measured_blank_length)
        if length is None:
            raise ValueError("Beam {} beam.blank has no measurable packing length".format(getattr(beam, "key", "?")))
        
        processed.append({
            "beam": beam,
            "geo": geo,
            "display_name": display_name,
            "module": module,
            "number": number,
            "beam_id": beam_id,
            "length": length,
            "measured_blank_length": measured_blank_length,
            "length_source": length_source
        })
    
    # Sort by length (descending) for optimal packing
    processed.sort(key=lambda x: x["length"], reverse=True)
    
    # Initialize output containers
    arr_boxes = []
    arr_names = []
    arr_lines = []
    dims = []
    num_txt = []
    stock_info = []
    
    total_len = 0
    current_x = origin.X
    
    # Layout each beam
    for item in processed:
        xform_nest = rg.Transform.Translation(current_x, origin.Y, origin.Z)
        
        # Position blank geometry on the packing line.
        g = duplicate_geometry(item["geo"])
        if g is None:
            continue
        bbox_before = g.GetBoundingBox(True)
        if bbox_before and bbox_before.IsValid:
            g.Transform(rg.Transform.Translation(-bbox_before.Min.X, -bbox_before.Min.Y, -bbox_before.Min.Z))
        g.Transform(xform_nest)
        arr_boxes.append(g)
        
        # Create and position label text
        text_geom = create_geometry_text(
            item["display_name"],
            rg.Point3d(current_x, origin.Y, origin.Z + label_offset),
            text_height=0.05
        )
        for curve in text_geom:
            arr_names.append(curve)
        
        # Reference line
        length = item["length"]
        arr_lines.append(
            rg.Line(
                rg.Point3d(current_x, origin.Y, origin.Z),
                rg.Point3d(current_x + length, origin.Y, origin.Z)
            )
        )
        
        # Record metadata
        dims.append(length)
        num_txt.append(f"L: {length:.2f}m")
        
        stock_info.append({
            "beam_id": item["beam_id"],
            "display_name": item["display_name"],
            "module": item["module"],
            "number": item["number"],
            "nested_position_x": current_x,
            "nested_length": length,
            "measured_blank_length": item["measured_blank_length"],
            "length_source": item["length_source"],
            "uses_beam_blank": True,
            "has_text_feature": True
        })
        
        total_len += length
        current_x += length + saw_gap
    
    # Generate production report
    report_lines = [
        "=== PRODUCTION REPORT ===",
        f"Total Length: {total_len:.2f} m",
        f"Total Cost: {total_len * price_lm:.2f} EUR",
        f"Total Items: {len(arr_boxes)}",
        "",
        "BREAKDOWN BY MODULE:"
    ]
    
    for module_letter in ["A", "B", "C", "D", "E", "F"]:
        beams_in_module = [b for b in stock_info if b["module"] == module_letter]
        if beams_in_module:
            report_lines.append(f"\n{module_letter}: {len(beams_in_module)} beams")
            for b in beams_in_module:
                report_lines.append(f"  └─ {b['display_name']} @ x={b['nested_position_x']:.2f}m | blank L={b['nested_length']:.2f}m")
    
    report = "\n".join(report_lines)
    
    return arr_boxes, arr_names, arr_lines, max(dims, default=0), dims, num_txt, stock_info, report
