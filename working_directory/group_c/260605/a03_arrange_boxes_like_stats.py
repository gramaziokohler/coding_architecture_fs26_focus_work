import Rhino.Geometry as rg
import rhinoscriptsyntax as rs


# ==============================================================================
# HELPERS
# ==============================================================================

def to_list(data):
    """
    Converts Grasshopper input to a normal Python list.
    Works with:
    - single item
    - list
    - tuple
    - Grasshopper DataTree
    """

    if data is None:
        return []

    if hasattr(data, "Branches"):
        result = []
        for branch in data.Branches:
            for item in branch:
                result.append(item)
        return result

    if isinstance(data, (list, tuple)):
        return list(data)

    return [data]


def coerce_to_geometry(obj):
    """
    Converts Guid / Box / Brep / Rhino geometry into usable Rhino geometry.
    This is important because Bounding Box can sometimes output Guid objects.
    """

    if obj is None:
        return None

    geo = rs.coercegeometry(obj)
    if geo is not None:
        return geo

    if isinstance(obj, rg.Box):
        return obj.ToBrep()

    if isinstance(obj, rg.Brep):
        return obj.DuplicateBrep()

    if isinstance(obj, rg.GeometryBase):
        return obj.Duplicate()

    if hasattr(obj, "ToBrep"):
        return obj.ToBrep()

    if hasattr(obj, "Duplicate"):
        return obj.Duplicate()

    return None


def duplicate_geometry(obj):
    geo = coerce_to_geometry(obj)

    if geo is None:
        return None

    if isinstance(geo, rg.Box):
        return geo.ToBrep()

    if isinstance(geo, rg.Brep):
        return geo.DuplicateBrep()

    if hasattr(geo, "Duplicate"):
        return geo.Duplicate()

    return geo


def get_bbox(geo):
    if geo is None:
        return None

    try:
        bbox = geo.GetBoundingBox(True)
        if bbox and bbox.IsValid:
            return bbox
    except:
        pass

    return None


# ==============================================================================
# MAIN FUNCTION
# ==============================================================================

def arrange_boxes_like_stats(
    boxes,
    names=None,
    horizontal_side_gap=0.01,
    row_tolerance=0.001,
    label_offset=0.03
):
    """
    Takes the max_len_box / Bounding Box result and rearranges it like the original
    Stats and Arrange layout.

    Important:
    - The existing row structure is preserved.
    - Rows are detected from the current Y position of the boxes.
    - Inside each row, boxes are ordered from left to right.
    - Every box gets horizontal space on the left and on the right.

    Parameters
    ----------
    boxes : list
        Bounding boxes / Breps from Grasshopper.

    names : list[str]
        Optional names.

    horizontal_side_gap : float
        Space on the left and right side of every beam box.
        If model is in meters:
        0.01 = 1 cm.

        This means:
        stock edge → 1 cm → beam → 1 cm → 1 cm → beam → 1 cm

        So the visible distance between two beams is 2 * horizontal_side_gap.

    row_tolerance : float
        Tolerance for detecting boxes that belong to the same row.

    label_offset : float
        Z offset for text labels.

    Returns
    -------
    arranged_boxes : list
    arranged_names : list
    label_points : list
    dimensions : list[str]
    report : str
    """

    boxes = to_list(boxes)
    names = to_list(names)

    horizontal_side_gap = float(horizontal_side_gap)
    row_tolerance = float(row_tolerance)
    label_offset = float(label_offset)

    # --------------------------------------------------------------------------
    # Read input boxes
    # --------------------------------------------------------------------------

    items = []

    for i, box in enumerate(boxes):

        geo = duplicate_geometry(box)

        if geo is None:
            continue

        bbox = get_bbox(geo)

        if bbox is None:
            continue

        length_x = bbox.Max.X - bbox.Min.X
        width_y = bbox.Max.Y - bbox.Min.Y
        height_z = bbox.Max.Z - bbox.Min.Z

        center_y = (bbox.Min.Y + bbox.Max.Y) / 2.0

        if i < len(names) and names[i] is not None:
            name = str(names[i])
        else:
            name = "B{:02d}".format(i + 1)

        items.append({
            "index": i,
            "geo": geo,
            "bbox": bbox,
            "name": name,
            "length_x": length_x,
            "width_y": width_y,
            "height_z": height_z,
            "center_y": center_y,
            "min_x": bbox.Min.X,
            "min_y": bbox.Min.Y,
            "min_z": bbox.Min.Z
        })

    if not items:
        return [], [], [], [], "No valid boxes received."

    # --------------------------------------------------------------------------
    # Group boxes by existing rows in Y
    # --------------------------------------------------------------------------

    sorted_by_y = sorted(items, key=lambda x: x["center_y"])

    rows = []

    for item in sorted_by_y:

        added = False

        for row in rows:
            row_center_y = row["center_y"]

            if abs(item["center_y"] - row_center_y) <= row_tolerance:
                row["items"].append(item)

                # update row center
                centers = [it["center_y"] for it in row["items"]]
                row["center_y"] = sum(centers) / float(len(centers))

                added = True
                break

        if not added:
            rows.append({
                "center_y": item["center_y"],
                "items": [item]
            })

    # Keep original visual order: top/bottom depends on your viewport,
    # but geometrically this keeps increasing Y.
    rows = sorted(rows, key=lambda r: r["center_y"])

    # --------------------------------------------------------------------------
    # Rearrange inside each row
    # --------------------------------------------------------------------------

    arranged_boxes = []
    arranged_names = []
    label_points = []
    dimensions = []

    for row_index, row in enumerate(rows):

        row_items = row["items"]

        # Original left edge of this stock row
        row_min_x = min(item["bbox"].Min.X for item in row_items)

        # Preserve original Y and Z placement of the row
        row_min_y = min(item["bbox"].Min.Y for item in row_items)
        row_min_z = min(item["bbox"].Min.Z for item in row_items)

        # Preserve left-to-right order from original Stats and Arrange
        row_items = sorted(row_items, key=lambda x: x["bbox"].Min.X)

        current_x = row_min_x + horizontal_side_gap

        for item in row_items:

            geo = item["geo"]
            bbox = item["bbox"]

            length_x = item["length_x"]
            width_y = item["width_y"]
            height_z = item["height_z"]
            name = item["name"]

            # Move box only according to the reconstructed packing row.
            # Y and Z stay aligned to the original row.
            move_x = current_x - bbox.Min.X
            move_y = row_min_y - bbox.Min.Y
            move_z = row_min_z - bbox.Min.Z

            transform = rg.Transform.Translation(move_x, move_y, move_z)
            geo.Transform(transform)

            arranged_boxes.append(geo)
            arranged_names.append(name)

            new_bbox = geo.GetBoundingBox(True)

            label_x = (new_bbox.Min.X + new_bbox.Max.X) / 2.0
            label_y = (new_bbox.Min.Y + new_bbox.Max.Y) / 2.0
            label_z = new_bbox.Max.Z + label_offset

            label_points.append(rg.Point3d(label_x, label_y, label_z))

            dimensions.append(
                "{} | row {} | X {:.4f} m | Y {:.4f} m | Z {:.4f} m".format(
                    name,
                    row_index + 1,
                    length_x,
                    width_y,
                    height_z
                )
            )

            # Important:
            # Every beam has 1 cm on the right.
            # The next beam starts after another 1 cm on its left.
            current_x += length_x + 2.0 * horizontal_side_gap

    # --------------------------------------------------------------------------
    # Report
    # --------------------------------------------------------------------------

    report = "\n".join([
        "--- ARRANGE BOXES LIKE STATS REPORT ---",
        "Input boxes: {}".format(len(boxes)),
        "Valid boxes: {}".format(len(items)),
        "Rows detected: {}".format(len(rows)),
        "Horizontal side gap: {:.4f} m".format(horizontal_side_gap),
        "Visible gap between two beams: {:.4f} m".format(2.0 * horizontal_side_gap),
        "Row tolerance: {:.4f} m".format(row_tolerance),
        "---------------------------------------"
    ])

    return (
        arranged_boxes,
        arranged_names,
        label_points,
        dimensions,
        report
    )