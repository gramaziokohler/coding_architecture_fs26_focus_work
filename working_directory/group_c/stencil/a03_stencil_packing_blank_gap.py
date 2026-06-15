from compas.geometry import Box
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Transformation
from compas.geometry import Vector
from compas_rhino.conversions import point_to_compas
import Rhino.Geometry as rg


# =============================================================================
# CONSTANTS
# =============================================================================

# Distanza reale desiderata tra la fine di un beam.blank / blanket
# e l'inizio del beam.blank / blanket successivo.
BLANK_TO_BLANK_GAP = 0.01

# Distanza dai bordi sinistro/destro dello stock commerciale.
STOCK_EDGE_GAP = 0.01


# =============================================================================
# HELPERS: NAME / FAMILY
# =============================================================================

def is_valid_custom_name(value):
    if value is None:
        return False

    txt = str(value).strip()

    if not txt:
        return False

    generic_names = [
        "beam",
        "beams",
        "element",
        "none",
        "null",
    ]

    if txt.lower() in generic_names:
        return False

    return True


def get_beam_name(beam, fallback=None):
    # 1. Prima prova: attributes["name"], ma solo se non è generico
    if hasattr(beam, "attributes") and isinstance(beam.attributes, dict):
        name = beam.attributes.get("name")
        if is_valid_custom_name(name):
            return str(name)

    # 2. Poi beam.name, ma ignora "Beam"
    if hasattr(beam, "name"):
        name = beam.name
        if is_valid_custom_name(name):
            return str(name)

    # 3. Poi user_name, se esiste
    if hasattr(beam, "user_name"):
        name = beam.user_name
        if is_valid_custom_name(name):
            return str(name)

    # 4. Altrimenti usa il fallback generato
    return fallback or "BEAM"


def get_beam_family(beam, tol=0.001):
    # 1. Prima prova: metadata
    if hasattr(beam, "attributes") and isinstance(beam.attributes, dict):
        fam = beam.attributes.get("family")
        if fam:
            return fam

    # 2. Fallback: riconoscimento da dimensioni SENZA sorted()
    try:
        w = round(float(beam.width), 3)
        h = round(float(beam.height), 3)
    except Exception:
        return "OTHER"

    # SF = frame beams: 8 x 6 cm
    # width/spessore = 0.080, height/altezza = 0.060
    if abs(w - 0.080) <= tol and abs(h - 0.060) <= tol:
        return "SF"

    # SP = plate beams: 6 x 8 cm
    # width/spessore = 0.060, height/altezza = 0.080
    if abs(w - 0.060) <= tol and abs(h - 0.080) <= tol:
        return "SP"

    return "OTHER"


def group_beams_by_family(timber_model):
    groups = {"SF": [], "SP": [], "OTHER": []}

    for beam in timber_model.beams:
        family = get_beam_family(beam)
        if family not in groups:
            groups[family] = []

        groups[family].append(beam)

    return groups


# =============================================================================
# HELPERS: BLANK / LENGTH
# =============================================================================

def get_beam_blank_geometry(beam):
    """Returns beam.blank / beam.blanket if available."""
    for attr in ["blank", "blanket"]:
        try:
            obj = getattr(beam, attr, None)
            if obj is not None:
                return obj
        except Exception:
            pass
    return None


def get_positive_float_attribute(obj, attr_names):
    if obj is None:
        return None, None

    for attr in attr_names:
        try:
            value = float(getattr(obj, attr))
            if value > 0:
                return value, attr
        except Exception:
            pass

    return None, None


def get_beam_packing_length(beam):
    """Length used for packing.

    Priority:
    1. beam.blank / beam.blanket length-like attributes
    2. beam length-like attributes
    3. beam.centerline.length fallback
    """
    blank = get_beam_blank_geometry(beam)

    blank_length, blank_attr = get_positive_float_attribute(
        blank,
        ["length", "lenght", "xsize", "x_size", "size_x"]
    )
    if blank_length is not None:
        return blank_length, "beam.blank.{}".format(blank_attr)

    beam_length, beam_attr = get_positive_float_attribute(
        beam,
        ["length", "lenght", "xsize", "x_size", "size_x"]
    )
    if beam_length is not None:
        return beam_length, "beam.{}".format(beam_attr)

    try:
        return float(beam.centerline.length), "beam.centerline.length fallback"
    except Exception:
        return 0.0, "no length found"


# =============================================================================
# HELPERS: FACE ORIENTATION
# =============================================================================

def get_original_top_face_key(beam):
    """Determina quale faccia locale del beam era rivolta verso l'alto nello stencil.

    Consideriamo le facce laterali del beam:
    +Y, -Y, +Z, -Z rispetto al frame locale del beam.
    La faccia con normale più vicina al Global Z viene considerata 'top face'.
    """
    try:
        candidates = [
            ("+Y", beam.frame.yaxis.z),
            ("-Y", -beam.frame.yaxis.z),
            ("+Z", beam.frame.zaxis.z),
            ("-Z", -beam.frame.zaxis.z),
        ]
        return max(candidates, key=lambda x: x[1])[0]
    except Exception:
        return "+Z"


def get_layout_yz_dimensions_for_beam(beam):
    """Restituisce le dimensioni Y/Z del beam nel layout stats and arrange.

    Se nello stencil la faccia +Y/-Y era sopra, allora nel layout il beam viene ruotato
    di 90° sulla sezione: la width va in Z e la height va in Y.
    """
    top_face = get_original_top_face_key(beam)

    try:
        w = float(beam.width)
        h = float(beam.height)
    except Exception:
        return 0.10, 0.10

    if top_face in ["+Y", "-Y"]:
        return h, w

    return w, h


def create_target_frame_preserving_top_face(beam, target_pt):
    """Crea un target frame mantenendo sopra la stessa faccia che era sopra nello stencil.

    L'asse locale X del beam rimane lungo lo stock, quindi lungo World X.
    Cambia solo la rotazione della sezione.
    """
    top_face = get_original_top_face_key(beam)

    x_axis = Vector(1, 0, 0)

    if top_face == "+Z":
        y_axis = Vector(0, 1, 0)

    elif top_face == "-Z":
        y_axis = Vector(0, -1, 0)

    elif top_face == "+Y":
        y_axis = Vector(0, 0, 1)

    elif top_face == "-Y":
        y_axis = Vector(0, 0, -1)

    else:
        y_axis = Vector(0, 1, 0)

    return Frame(target_pt, x_axis, y_axis)


# =============================================================================
# HELPERS: GEOMETRY / TEXT
# =============================================================================

def create_blank_layout_box(item, start_x, y_pos, z_pos, beam_offset=0.0):
    """Creates an aligned visual box representing the packed beam.blank envelope."""
    beam = item["beam"]
    length = item["length"]

    y_dim, z_dim = get_layout_yz_dimensions_for_beam(beam)

    center_x = start_x + length / 2.0
    center_pt = Point(center_x, y_pos + beam_offset, z_pos)
    box_frame = Frame(center_pt, Vector(1, 0, 0), Vector(0, 1, 0))

    return Box(length, y_dim, z_dim, frame=box_frame)


def create_centered_text(text, position, text_height=0.04):
    """Creates a centered Rhino TextEntity at the given COMPAS Point."""
    te = rg.TextEntity()
    te.Text = str(text)
    te.FontIndex = 0
    te.TextHeight = text_height

    plane = rg.Plane.WorldXY
    plane.Origin = rg.Point3d(position.x, position.y, position.z)
    te.Plane = plane

    bbox = te.GetBoundingBox(True)

    if bbox.IsValid:
        cx = (bbox.Min.X + bbox.Max.X) / 2.0
        cy = (bbox.Min.Y + bbox.Max.Y) / 2.0
        cz = (bbox.Min.Z + bbox.Max.Z) / 2.0

        te.Transform(
            rg.Transform.Translation(
                position.x - cx,
                position.y - cy,
                position.z - cz
            )
        )

    return te


def compas_point_to_rhino_point(pt):
    if hasattr(pt, "X"):
        return pt
    return rg.Point3d(pt.x, pt.y, pt.z)


def compas_vector_to_rhino_vector(vec):
    return rg.Vector3d(vec.x, vec.y, vec.z)


def get_beam_midpoint(beam):
    try:
        return beam.centerline.point_at(0.5)
    except Exception:
        try:
            return beam.frame.point
        except Exception:
            return None


def create_centered_beam_text_onplace(text, beam, text_height=0.06, z_offset=0.015):
    """Creates a Rhino TextEntity directly on the original stencil beam."""
    mid = get_beam_midpoint(beam)
    if mid is None:
        return None

    origin = compas_point_to_rhino_point(mid)

    xaxis = compas_vector_to_rhino_vector(beam.frame.xaxis)
    yaxis = compas_vector_to_rhino_vector(beam.frame.yaxis)
    zaxis = compas_vector_to_rhino_vector(beam.frame.zaxis)

    try:
        h = float(beam.height)
    except Exception:
        h = 0.08

    # Testo leggermente sopra il beam originale / in-place
    origin = origin + zaxis * (h / 2.0 + z_offset)

    plane = rg.Plane(origin, xaxis, yaxis)

    te = rg.TextEntity()
    te.Text = str(text)
    te.FontIndex = 0
    te.TextHeight = text_height
    te.Plane = plane

    bbox = te.GetBoundingBox(True)

    if bbox.IsValid:
        cx = (bbox.Min.X + bbox.Max.X) / 2.0
        cy = (bbox.Min.Y + bbox.Max.Y) / 2.0
        cz = (bbox.Min.Z + bbox.Max.Z) / 2.0

        te.Transform(
            rg.Transform.Translation(
                origin.X - cx,
                origin.Y - cy,
                origin.Z - cz
            )
        )

    return te


def create_stencil_beam_name_onplace(grouped_stocks, text_height=0.06, z_offset=0.015):
    """Creates beam names on the original stencil, using names stored in grouped_stocks."""
    texts = []
    seen = set()

    for family, stocks in grouped_stocks.items():
        for stock in stocks:
            for item in stock.get("beams", []):
                beam = item.get("beam")
                name = item.get("name")

                if beam is None or name is None:
                    continue

                key = id(beam)
                if key in seen:
                    continue
                seen.add(key)

                try:
                    text_obj = create_centered_beam_text_onplace(
                        name,
                        beam,
                        text_height=text_height,
                        z_offset=z_offset,
                    )
                    if text_obj is not None:
                        texts.append(text_obj)
                except Exception as e:
                    print("ONPLACE TEXT ERROR for {}: {}".format(name, e))

    return texts


# =============================================================================
# GENERAL STATS
# =============================================================================

def get_group_stats(beams, group_name, wood_density=500):
    if not beams:
        return [
            "{}: 0 beams".format(group_name)
        ]

    lengths = [b.centerline.length for b in beams]
    total_length = sum(lengths)

    total_volume = 0.0
    for b in beams:
        try:
            total_volume += b.geometry.volume
        except Exception:
            pass

    total_weight = total_volume * wood_density

    return [
        "{}: {} beams".format(group_name, len(beams)),
        "  total length = {:.3f} m".format(total_length),
        "  total weight = {:.1f} kg".format(total_weight),
    ]


def get_general_stats_grouped(timber_model, wood_density=500):
    groups = group_beams_by_family(timber_model)

    all_beams = list(timber_model.beams)
    total_count = len(all_beams)
    total_length = sum(b.centerline.length for b in all_beams) if all_beams else 0.0

    lines = [
        "--- STENCIL MODEL STATS ---",
        "Total beams: {}".format(total_count),
        "Total length: {:.3f} m".format(total_length),
        "---------------------------",
    ]

    for key in ["SF", "SP", "OTHER"]:
        if key in groups and groups[key]:
            lines.extend(get_group_stats(groups[key], key, wood_density))
            lines.append("---------------------------")

    msg = "\n".join(lines)
    print(msg)
    return msg


# =============================================================================
# BIN PACKING
# =============================================================================

def solve_bin_packing_for_beams(
    beams,
    stock_length,
    saw_kerf=0.0,
    blank_to_blank_gap=BLANK_TO_BLANK_GAP,
    stock_edge_gap=STOCK_EDGE_GAP,
):
    beam_data = []

    # Spazio visibile minimo 1 cm. Se saw_kerf è più grande, vince saw_kerf.
    try:
        effective_gap = max(float(blank_to_blank_gap), float(saw_kerf))
    except Exception:
        effective_gap = float(blank_to_blank_gap)

    usable_stock_length = float(stock_length) - (2.0 * float(stock_edge_gap))

    for i, beam in enumerate(beams):
        packing_length, length_source = get_beam_packing_length(beam)
        family = get_beam_family(beam)

        beam_data.append(
            {
                "beam": beam,
                "original_index": i,
                "length": packing_length,
                "needed_len": packing_length + effective_gap,
                "name": get_beam_name(
                    beam,
                    "{}{}".format(family, i + 1)
                ),
                "length_source": length_source,
            }
        )

    sorted_beams = sorted(beam_data, key=lambda x: x["length"], reverse=True)

    stocks = []

    for item in sorted_beams:
        needed = item["needed_len"]
        placed = False

        for stock in stocks:
            if stock["remaining"] >= needed:
                current_start = stock["current_pos"]

                stock["beams"].append(
                    {
                        "beam": item["beam"],
                        "name": item["name"],
                        "start_pos": current_start,
                        "visual_start_x": current_start + stock_edge_gap,
                        "length": item["length"],
                        "needed_len": item["needed_len"],
                        "length_source": item["length_source"],
                    }
                )

                stock["remaining"] -= needed
                stock["current_pos"] += needed
                placed = True
                break

        if not placed:
            new_stock = {
                "id": len(stocks) + 1,
                "stock_length": stock_length,
                "usable_stock_length": usable_stock_length,
                "stock_edge_gap": stock_edge_gap,
                "blank_to_blank_gap": effective_gap,
                "remaining": usable_stock_length - needed,
                "current_pos": needed,
                "beams": [
                    {
                        "beam": item["beam"],
                        "name": item["name"],
                        "start_pos": 0.0,
                        "visual_start_x": stock_edge_gap,
                        "length": item["length"],
                        "needed_len": item["needed_len"],
                        "length_source": item["length_source"],
                    }
                ],
            }
            stocks.append(new_stock)

    return stocks


def solve_grouped_bin_packing(
    timber_model,
    stock_length_frame,
    stock_length_plate,
    saw_kerf=0.0,
):
    groups = group_beams_by_family(timber_model)

    grouped_stocks = {
        "SF": solve_bin_packing_for_beams(groups["SF"], stock_length_frame, saw_kerf),
        "SP": solve_bin_packing_for_beams(groups["SP"], stock_length_plate, saw_kerf),
    }

    if groups.get("OTHER"):
        grouped_stocks["OTHER"] = solve_bin_packing_for_beams(
            groups["OTHER"], stock_length_frame, saw_kerf
        )

    return grouped_stocks


# =============================================================================
# VISUALIZATION
# =============================================================================

def visualize_grouped_packing(
    grouped_stocks,
    origin,
    stock_length_frame,
    stock_length_plate,
    beam_spacing=0.25,
    beam_offset=0.0,
    group_gap=0.50,
    label_offset=0.05,
):
    visual_stocks = []
    visual_beams = []
    visual_beam_blanks = []
    beam_labels = []
    beam_label_points = []
    beam_name_texts = []

    if hasattr(origin, "X"):
        origin = point_to_compas(origin)

    base_x = origin.x
    base_y = origin.y
    base_z = origin.z

    current_y = base_y

    group_order = ["SF", "SP", "OTHER"]

    for family in group_order:
        if family not in grouped_stocks:
            continue

        stocks = grouped_stocks[family]
        if not stocks:
            continue

        stock_length = stock_length_frame if family != "SP" else stock_length_plate

        for i, stock in enumerate(stocks):
            y_pos = current_y + i * beam_spacing

            if stock["beams"]:
                dims = [
                    get_layout_yz_dimensions_for_beam(item["beam"])
                    for item in stock["beams"]
                ]
                w = max(d[0] for d in dims)
                h = max(d[1] for d in dims)
            else:
                w, h = 0.1, 0.1

            center_x = base_x + stock_length / 2.0
            center_pt = Point(center_x, y_pos, base_z)
            box_frame = Frame(center_pt, Vector(1, 0, 0), Vector(0, 1, 0))
            stock_box = Box(stock_length, w, h, frame=box_frame)
            visual_stocks.append(stock_box)

            for item in stock["beams"]:
                beam = item["beam"]

                # visual_start_x include 1 cm dal bordo dello stock.
                start_x = base_x + item["visual_start_x"]

                target_pt = Point(start_x, y_pos + beam_offset, base_z)
                target_frame = create_target_frame_preserving_top_face(beam, target_pt)

                source_frame = beam.frame
                X = Transformation.from_frame_to_frame(source_frame, target_frame)

                # Geometria finale/tagliata del beam nello stats and arrange.
                try:
                    new_geo = beam.geometry.transformed(X)
                    visual_beams.append(new_geo)
                except Exception:
                    pass

                # Box di controllo del beam.blank / blanket.
                try:
                    blank_box = create_blank_layout_box(
                        item=item,
                        start_x=start_x,
                        y_pos=y_pos,
                        z_pos=base_z,
                        beam_offset=beam_offset,
                    )
                    visual_beam_blanks.append(blank_box)
                except Exception as e:
                    print("BLANK BOX ERROR for {}: {}".format(item.get("name", "?"), e))

                _, beam_layout_z_dim = get_layout_yz_dimensions_for_beam(beam)

                label_pt = Point(
                    start_x + item["length"] / 2.0,
                    y_pos + beam_offset,
                    base_z + beam_layout_z_dim / 2.0 + label_offset,
                )

                beam_labels.append(item["name"])
                beam_label_points.append(label_pt)

                try:
                    beam_name_texts.append(
                        create_centered_text(
                            item["name"],
                            label_pt,
                            text_height=0.04
                        )
                    )
                except Exception as e:
                    print("TEXT ERROR for {}: {}".format(item.get("name", "?"), e))

        current_y += len(stocks) * beam_spacing + group_gap

    return (
        visual_stocks,
        visual_beams,
        visual_beam_blanks,
        beam_labels,
        beam_label_points,
        beam_name_texts,
    )


# =============================================================================
# PACKING STATS
# =============================================================================

def get_packing_stats_for_group(stocks, stock_length, family):
    if not stocks:
        return [
            "{}: no stocks".format(family)
        ]

    num_stocks = len(stocks)
    total_stock_bought = num_stocks * stock_length

    total_edge_waste = 0.0
    if stocks:
        total_edge_waste = sum(2.0 * stock.get("stock_edge_gap", STOCK_EDGE_GAP) for stock in stocks)

    total_waste = sum(stock["remaining"] for stock in stocks) + total_edge_waste
    used_length = total_stock_bought - total_waste
    efficiency = (used_length / total_stock_bought * 100.0) if total_stock_bought > 0 else 0.0

    lines = [
        "{}".format(family),
        "  stock length = {:.3f} m".format(stock_length),
        "  stocks needed = {}".format(num_stocks),
        "  total material = {:.3f} m".format(total_stock_bought),
        "  waste incl. stock edge gaps = {:.3f} m".format(total_waste),
        "  efficiency = {:.1f}%".format(efficiency),
        "  blank-to-blank gap = {:.3f} m".format(stocks[0].get("blank_to_blank_gap", BLANK_TO_BLANK_GAP)),
        "  stock edge gap each side = {:.3f} m".format(stocks[0].get("stock_edge_gap", STOCK_EDGE_GAP)),
    ]

    source_lines = []
    for stock in stocks:
        for item in stock.get("beams", []):
            source_lines.append(
                "    {}: {:.3f} m ({})".format(
                    item.get("name", "?"),
                    item.get("length", 0.0),
                    item.get("length_source", "unknown")
                )
            )

    if source_lines:
        lines.append("  packing lengths:")
        lines.extend(source_lines)

    return lines


def get_grouped_packing_stats(grouped_stocks, stock_length_frame, stock_length_plate):
    lines = ["--- STENCIL PACKING REPORT ---"]

    if "SF" in grouped_stocks:
        lines.extend(get_packing_stats_for_group(grouped_stocks["SF"], stock_length_frame, "SF"))
        lines.append("------------------------------")

    if "SP" in grouped_stocks:
        lines.extend(get_packing_stats_for_group(grouped_stocks["SP"], stock_length_plate, "SP"))
        lines.append("------------------------------")

    if "OTHER" in grouped_stocks:
        lines.extend(get_packing_stats_for_group(grouped_stocks["OTHER"], stock_length_frame, "OTHER"))
        lines.append("------------------------------")

    msg = "\n".join(lines)
    print(msg)
    return msg


# =============================================================================
# MAIN
# =============================================================================

def solve_and_visualize_stencil_packing(
    timber_model,
    origin,
    stock_length_frame,
    stock_length_plate,
    saw_gap=0.0,
    beam_spacing=0.25,
    beam_offset=0.0,
    group_gap=0.50,
    label_offset=0.05,
    wood_density=500,
):
    model_stats = get_general_stats_grouped(
        timber_model,
        wood_density=wood_density
    )

    grouped_stocks = solve_grouped_bin_packing(
        timber_model=timber_model,
        stock_length_frame=stock_length_frame,
        stock_length_plate=stock_length_plate,
        saw_kerf=saw_gap,
    )

    stencil_beam_name_onplace = create_stencil_beam_name_onplace(
        grouped_stocks,
        text_height=0.06,
        z_offset=0.015,
    )

    (
        visual_stocks,
        visual_beams,
        visual_beam_blanks,
        beam_labels,
        beam_label_points,
        beam_name_texts,
    ) = visualize_grouped_packing(
        grouped_stocks=grouped_stocks,
        origin=origin,
        stock_length_frame=stock_length_frame,
        stock_length_plate=stock_length_plate,
        beam_spacing=beam_spacing,
        beam_offset=beam_offset,
        group_gap=group_gap,
        label_offset=label_offset,
    )

    packing_stats = get_grouped_packing_stats(
        grouped_stocks=grouped_stocks,
        stock_length_frame=stock_length_frame,
        stock_length_plate=stock_length_plate,
    )

    return (
        model_stats,
        packing_stats,
        visual_stocks,
        visual_beams,
        beam_labels,
        beam_label_points,
        grouped_stocks,
        visual_beam_blanks,
        beam_name_texts,
        stencil_beam_name_onplace,
    )