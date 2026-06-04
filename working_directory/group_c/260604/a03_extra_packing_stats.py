from compas.geometry import Frame
from compas.geometry import Transformation
from compas_rhino.conversions import point_to_compas


def basic_arrange_beams(timber_model, origin, gap):
    origin = point_to_compas(point)

    frame = Frame(origin, [0, 1, 0], [0, 0, 1])
    beam_grid = []
    for i, beam in enumerate(timber_model.beams):
        stock_beam = beam.geometry
        trans = Transformation.from_frame_to_frame(beam.frame, frame)
        stock_beam = stock_beam.transformed(trans)
        beam_grid.append(stock_beam)
        frame.point.x += gap


def get_general_stats(timber_model, wood_density=500):
    """
    Erstellt allgemeine Statistiken über das Timber-Modell.
    wood_density: Dichte in kg/m3 (Standard ca. 500 für Nadelholz)
    """
    beams = list(timber_model.beams)

    # 1. Basis Geometrie
    count = len(beams)
    lengths = [b.centerline.length for b in beams]
    total_length = sum(lengths)
    min_len = min(lengths) if lengths else 0
    max_len = max(lengths) if lengths else 0

    # 2. Masse (Volumen & Gewicht)
    total_volume = sum(b.geometry.volume for b in beams)
    total_weight = total_volume * wood_density

    # 3. Features & Bearbeitungen
    total_joints = sum(len(b.joints) for b in beams if hasattr(b, "joints"))
    total_features = sum(len(b.features) for b in beams if hasattr(b, "features"))

    stats_msg = "\n".join(
        [
            "--- MODEL STATS ---",
            f"Beams: {count}",
            f"Total Length: {total_length:.2f} m",
            f"Longest Beam: {max_len:.2f} m",
            f"Weight: {total_weight:.1f} kg",
            f"Joints/Features: {total_joints} / {total_features}",
            "-------------------",
        ]
    )

    print(stats_msg)

    return stats_msg


def solve_bin_packing(timber_model, stock_length, saw_kerf=0.0):
    """
    Kerns-Logik für Bin Packing (First Fit Decreasing).

    Returns:
        list: Liste von Dictionaries (Stocks), die jeweils die gepackten Balken enthalten.
    """
    # 1. Daten extrahieren und vorbereiten
    beams = list(timber_model.beams)
    beam_data = []
    for i, beam in enumerate(beams):
        l = beam.centerline.length
        beam_data.append({"beam": beam, "original_index": i, "length": l, "needed_len": l + saw_kerf})

    # 2. Sortieren: Längste Balken zuerst (First Fit Decreasing)
    sorted_beams = sorted(beam_data, key=lambda x: x["length"], reverse=True)

    stocks = []

    # 3. Packing Loop
    for item in sorted_beams:
        needed = item["needed_len"]
        placed = False

        # Versuche in existierende Stocks einzufügen
        for stock in stocks:
            if stock["remaining"] >= needed:
                # Add to stock
                current_start = stock["current_pos"]
                stock["beams"].append({"beam": item["beam"], "start_pos": current_start, "length": item["length"]})

                # Update stock stats
                stock["remaining"] -= needed
                stock["current_pos"] += needed
                placed = True
                break

        if not placed:
            # Erstelle neuen Stock
            new_stock = {
                "id": len(stocks),
                "remaining": stock_length - needed,
                "current_pos": needed,
                "beams": [{"beam": item["beam"], "start_pos": 0.0, "length": item["length"]}],
            }
            stocks.append(new_stock)

    return stocks


def visualize_packing(stocks, origin, stock_length, beam_spacing=0.6, beam_offset=0.2):
    """
    Erzeugt Visualisierungs-Geometrie aus dem Packing-Resultat.

    Args:
        stocks (list): Das Ergebnis von solve_bin_packing.
        origin (Point): Startpunkt für die Visualisierung.
        stock_length (float): Die visuelle Länge der Rohbalken.
        beam_spacing (float): Abstand zwischen den Rohbalken in Y.
        beam_offset (float): Abstand der gepackten Balken zum Rohbalken in Y.

    Returns:
        tuple: (stock_geometries, packed_beam_geometries)
    """
    # Imports falls nötig (hier gehen wir davon aus, dass sie im Scope sind,
    # aber sicherheitshalber importieren wir Transformation und Frame für die Logik)
    from compas.geometry import Box
    from compas.geometry import Frame
    from compas.geometry import Line
    from compas.geometry import Point
    from compas.geometry import Transformation
    from compas.geometry import Vector

    visual_stocks = []
    visual_beams = []

    base_x = origin.x
    base_y = origin.y
    base_z = origin.z

    for i, stock in enumerate(stocks):
        y_pos = base_y + (i * beam_spacing)

        # 1. Erzeuge Stock-Geometrie (als Hintergrund)
        # Wir nutzen width/height des ersten Balkens im Stock als Referenz
        if stock["beams"]:
            ref_beam = stock["beams"][0]["beam"]
            w = ref_beam.width
            h = ref_beam.height
        else:
            w, h = 0.1, 0.1

        # Erstelle Box Geometrie für den Stock
        # Box Zentrum berechnen
        center_x = base_x + stock_length / 2
        center_pt = Point(center_x, y_pos, base_z)

        # Frame für die Box (Zentrum)
        box_frame = Frame(center_pt, Vector(1, 0, 0), Vector(0, 1, 0))

        # Box(xsize, ysize, zsize, frame)
        # xsize ist hier die Länge des Stocks
        stock_box = Box(stock_length, w, h, frame=box_frame)
        visual_stocks.append(stock_box)

        # 2. Transformiere die gepackten Balken
        for item in stock["beams"]:
            beam = item["beam"]
            start_x = base_x + item["start_pos"]

            # Ziel-Frame:
            # Position: start_x, y_pos + offset, base_z
            # Orientierung: Global X
            target_pt = Point(start_x, y_pos + beam_offset, base_z)
            target_frame = Frame(target_pt, Vector(1, 0, 0), Vector(0, 1, 0))

            # Quell-Frame des Balkens
            source_frame = beam.frame

            # Transformation
            X = Transformation.from_frame_to_frame(source_frame, target_frame)

            # Geometrie kopieren und transformieren
            if hasattr(beam, "geometry") and beam.geometry:
                new_geo = beam.geometry.transformed(X)
                visual_beams.append(new_geo)

    return visual_stocks, visual_beams


def get_packing_stats(stocks, stock_length, price_per_meter=5.00, currency="CHF"):
    """
    Erzeugt einen Bericht über die Effizienz und Kosten des Packings.
    """
    if not stocks:
        return {}

    # 1. Basis Werte
    num_stocks = len(stocks)
    total_stock_bought = num_stocks * stock_length

    # 2. Verschnitt Berechnung
    # Wir summieren den 'remaining' Wert jedes Stocks
    total_waste = sum(stock["remaining"] for stock in stocks)
    used_length = total_stock_bought - total_waste

    # 3. Effizienz
    efficiency = 0
    if total_stock_bought > 0:
        efficiency = (used_length / total_stock_bought) * 100

    # 4. Kosten
    total_cost = total_stock_bought * price_per_meter

    # Ausgabe formatieren

    msg = "\n".join(
        [
            "--- PACKING REPORT ---",
            f"Stock Length used: {stock_length} m",
            f"Stocks needed:     {num_stocks} pcs",
            f"Total Material:    {total_stock_bought:.2f} m",
            "----------------------",
            f"Total Waste:       {total_waste:.2f} m",
            f"Efficiency:        {efficiency:.1f}%",
            "----------------------",
            f"Price/m:           {price_per_meter} {currency}",
            f"ESTIMATED COST:    {total_cost:.2f} {currency}",
            "----------------------",
        ]
    )

    print(msg)

    # Rückgabe als String für Text Panel
    return msg

# ==============================================================================
# GROUPED PACKING BY CROSS SECTION / QUERSCHNITT
# ==============================================================================

def get_beam_cross_section(beam, precision=4):
    """
    Reads the beam cross-section and returns it as a tuple:
    (width, height)

    Example:
        (0.06, 0.08)
        (0.12, 0.14)

    The rounding avoids floating point issues like 0.06000000001.
    """

    width = None
    height = None

    if hasattr(beam, "width"):
        width = beam.width

    if hasattr(beam, "height"):
        height = beam.height

    if width is None or height is None:
        if hasattr(beam, "__dict__"):
            data = beam.__dict__

            possible_width_names = [
                "width",
                "beam_width",
                "section_width",
                "cross_section_width",
                "b",
            ]

            possible_height_names = [
                "height",
                "beam_height",
                "section_height",
                "cross_section_height",
                "h",
            ]

            if width is None:
                for name in possible_width_names:
                    if name in data:
                        width = data[name]
                        break

            if height is None:
                for name in possible_height_names:
                    if name in data:
                        height = data[name]
                        break

    if width is None or height is None:
        return ("unknown", "unknown")

    return (round(float(width), precision), round(float(height), precision))


class BeamSubsetModel(object):
    """
    Small wrapper so that solve_bin_packing() can receive only
    a subset of beams while still behaving like a timber_model.
    """

    def __init__(self, beams):
        self.beams = beams


def group_beams_by_cross_section(timber_model):
    """
    Groups beams by their cross-section.

    Returns:
        dict:
        {
            (0.06, 0.08): [beam1, beam2, ...],
            (0.12, 0.14): [beam3, beam4, ...]
        }
    """

    groups = {}

    for beam in timber_model.beams:
        section = get_beam_cross_section(beam)

        if section not in groups:
            groups[section] = []

        groups[section].append(beam)

    return groups


def solve_grouped_bin_packing(timber_model, stock_length, saw_kerf=0.0):
    """
    Runs bin packing separately for every cross-section / Querschnitt.

    This prevents beams with different dimensions from being packed
    into the same stock.
    """

    groups = group_beams_by_cross_section(timber_model)

    grouped_stocks = {}

    for section in sorted(groups.keys()):
        beams = groups[section]
        subset_model = BeamSubsetModel(beams)

        stocks = solve_bin_packing(
            subset_model,
            stock_length,
            saw_kerf
        )

        grouped_stocks[section] = stocks

    return grouped_stocks


def visualize_grouped_packing(
    grouped_stocks,
    origin,
    stock_length,
    beam_spacing=0.6,
    beam_offset=0.2,
    group_spacing=None
):
    """
    Visualizes grouped packing.

    Each cross-section group is displayed separately in Y direction.
    """

    from compas.geometry import Point

    if group_spacing is None:
        group_spacing = beam_spacing * 3.0

    visual_stocks_all = []
    visual_beams_all = []
    section_labels = []
    section_label_points = []

    base_x = origin.x
    base_y = origin.y
    base_z = origin.z

    y_offset = 0.0

    for section in sorted(grouped_stocks.keys()):
        stocks = grouped_stocks[section]

        section_origin = Point(
            base_x,
            base_y + y_offset,
            base_z
        )

        visual_stocks, visual_beams = visualize_packing(
            stocks,
            section_origin,
            stock_length,
            beam_spacing,
            beam_offset
        )

        visual_stocks_all.extend(visual_stocks)
        visual_beams_all.extend(visual_beams)

        label = format_cross_section_label(section)
        section_labels.append(label)

        label_point = Point(
            base_x,
            base_y + y_offset - beam_spacing * 0.6,
            base_z
        )
        section_label_points.append(label_point)

        y_offset += len(stocks) * beam_spacing + group_spacing

    return visual_stocks_all, visual_beams_all, section_labels, section_label_points


def format_cross_section_label(section):
    """
    Formats cross-section label for Grasshopper display.
    """

    width, height = section

    if width == "unknown" or height == "unknown":
        return "Querschnitt unknown"

    return "Querschnitt {:.2f} x {:.2f} m".format(width, height)


def get_grouped_packing_stats(
    grouped_stocks,
    stock_length,
    price_per_meter=5.00,
    currency="CHF"
):
    """
    Creates one packing report per cross-section and one total summary.
    """

    reports = []

    total_stocks = 0
    total_material = 0.0
    total_waste = 0.0
    total_cost = 0.0

    for section in sorted(grouped_stocks.keys()):
        stocks = grouped_stocks[section]

        label = format_cross_section_label(section)

        num_stocks = len(stocks)
        material = num_stocks * stock_length
        waste = sum(stock["remaining"] for stock in stocks)
        cost = material * price_per_meter

        total_stocks += num_stocks
        total_material += material
        total_waste += waste
        total_cost += cost

        efficiency = 0.0
        if material > 0:
            efficiency = ((material - waste) / material) * 100.0

        report = "\n".join(
            [
                "--- PACKING REPORT: {} ---".format(label),
                "Stock Length used: {:.2f} m".format(stock_length),
                "Stocks needed:     {} pcs".format(num_stocks),
                "Total Material:    {:.2f} m".format(material),
                "Total Waste:       {:.2f} m".format(waste),
                "Efficiency:        {:.1f}%".format(efficiency),
                "Price/m:           {} {}".format(price_per_meter, currency),
                "Estimated Cost:    {:.2f} {}".format(cost, currency),
                "----------------------",
            ]
        )

        reports.append(report)

    total_efficiency = 0.0
    if total_material > 0:
        total_efficiency = ((total_material - total_waste) / total_material) * 100.0

    total_report = "\n".join(
        [
            "--- TOTAL PACKING SUMMARY ---",
            "Total Stocks needed: {} pcs".format(total_stocks),
            "Total Material:      {:.2f} m".format(total_material),
            "Total Waste:         {:.2f} m".format(total_waste),
            "Total Efficiency:    {:.1f}%".format(total_efficiency),
            "Total Cost:          {:.2f} {}".format(total_cost, currency),
            "-----------------------------",
        ]
    )

    reports.append(total_report)

    msg = "\n\n".join(reports)
    print(msg)

    return msg


def solve_and_visualize_grouped_packing(
    timber_model,
    origin,
    stock_length,
    saw_gap,
    beam_spacing,
    beam_offset,
    price_lm,
    currency="CHF"
):
    """
    Main function for Grasshopper.

    It does everything:
    1. model stats
    2. group beams by cross-section
    3. bin packing per cross-section
    4. visualization
    5. packing statistics
    """

    from compas_rhino.conversions import point_to_compas

    model_stats = get_general_stats(timber_model)

    origin = point_to_compas(origin)

    grouped_stocks = solve_grouped_bin_packing(
        timber_model,
        stock_length,
        saw_gap
    )

    visual_stocks, visual_beams, section_labels, section_label_points = visualize_grouped_packing(
        grouped_stocks,
        origin,
        stock_length,
        beam_spacing,
        beam_offset
    )

    packing_stats = get_grouped_packing_stats(
        grouped_stocks,
        stock_length,
        price_lm,
        currency
    )

    return (
        model_stats,
        packing_stats,
        visual_stocks,
        visual_beams,
        section_labels,
        section_label_points,
        grouped_stocks
    )