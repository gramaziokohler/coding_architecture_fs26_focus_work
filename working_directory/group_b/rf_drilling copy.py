import math
from compas.geometry import Point, Vector, Line, intersection_line_line, distance_point_point
from compas_timber.fabrication import Drilling
from compas_timber.connections import (
    LMiterJoint,
    TBirdsmouthJoint,
    TButtJoint,
    TLapJoint,
    XLapJoint,
    TStepJoint
)

class DrillingProcessor:
    """
    A helper class to apply Drilling features (screws/dowels) to the joints 
    of a generated TimberModel and track process statistics.
    """
    def __init__(self, timber_model, screw_diameter=0.006, screw_length=0.150, screw_spacing=0.040, max_drilling_depth=None):
        self.timber_model = timber_model
        self.screw_diameter = screw_diameter
        self.screw_length = screw_length
        self.screw_spacing = screw_spacing 
        self.max_drilling_depth = max_drilling_depth
        
        self.drilling_count = 0
        self.screw_lines = []
        self.failed_screw_info = []
        self.summary_text = ""
        
        self.processed_beam_pairs = set()
        
        # Procurement tracking
        self.screw_stats_by_type = {}
        self.miter_counts = {}

    def process_drillings(self):
        print("--- Starting Drilling Generation ---")
        
        self.drilling_count = 0
        self.screw_lines = []
        self.failed_screw_info = []
        self.summary_text = "" 
        self.processed_beam_pairs = set()
        self.screw_stats_by_type = {}
        self.miter_counts = {}
        
        # Cleanup ghost drillings
        for beam in self.timber_model.beams:
            if hasattr(beam, 'features'):
                old_drillings = [f for f in beam.features if isinstance(f, Drilling)]
                for d in old_drillings:
                    try:
                        beam.remove_feature(d)
                    except AttributeError:
                        beam.features.remove(d)
        
        joints = getattr(self.timber_model, 'joints', None) or getattr(self.timber_model, 'interactions', [])
        
        for joint in joints:
            # 1. EXTRACT ELEMENTS FOR DEDUPLICATION
            elements = getattr(joint, 'elements', None)
            if not elements and hasattr(joint, 'main_beam'):
                elements = [joint.main_beam, getattr(joint, 'cross_beam')]
                
            if not elements or len(elements) < 2 or not elements[0] or not elements[1]:
                continue
                
            # 2. BULLETPROOF DEDUPLICATION
            def get_uid(beam):
                if "edge" in beam.attributes:
                    return str(beam.attributes["edge"])
                else:
                    mid = beam.centerline.midpoint
                    return f"{round(mid.x, 3)}_{round(mid.y, 3)}_{round(mid.z, 3)}"
                    
            uid_a = get_uid(elements[0])
            uid_b = get_uid(elements[1])
            pair_id = frozenset([uid_a, uid_b])
            
            if pair_id in self.processed_beam_pairs:
                continue 
                
            self.processed_beam_pairs.add(pair_id)
            
            # 3. PROCEED WITH DRILLING & CATEGORIZATION
            if isinstance(joint, TButtJoint):
                self._apply_butt_drilling(joint, elements[0], elements[1])
            elif isinstance(joint, (XLapJoint, TLapJoint)):
                self._apply_lap_drilling(joint, elements[0], elements[1])
            elif isinstance(joint, LMiterJoint):
                # Count the miters for the summary math instead of drawing drill lines
                cat1 = elements[0].attributes.get("category", "inner")
                cat2 = elements[1].attributes.get("category", "inner")
                if cat1 == "base" or cat2 == "base":
                    label = "Lmitter foundation"
                else:
                    label = "Lmitter arch"
                    
                self.miter_counts[label] = self.miter_counts.get(label, 0) + 1
            
        # --- COMPILE PROCUREMENT SUMMARY TEXT ---
        log = []
        log.append("================ PROCUREMENT & DRILLING SUMMARY ================")
        log.append(f"Unique Joints Processed: {len(self.processed_beam_pairs)}")
        log.append("----------------------------------------------------------------")
        
        total_screws_overall = 0
        
        # Process physically drilled joints (Butt, Lap, etc)
        for j_type in sorted(self.screw_stats_by_type.keys()):
            lengths = self.screw_stats_by_type[j_type]
            num_screws = len(lengths)
            total_screws_overall += num_screws
            
            if num_screws > 0:
                min_len = min(lengths)
                max_len = max(lengths)
                log.append(f"[{j_type}]")
                log.append(f"  -> Total Screws : {num_screws}")
                log.append(f"  -> Shortest Hole: {min_len * 1000:.1f} mm")
                log.append(f"  -> Longest Hole : {max_len * 1000:.1f} mm")
                log.append("")
                
        # Process Miter Joints using the requested multiplier logic
        for m_type in sorted(self.miter_counts.keys()):
            count = self.miter_counts[m_type]
            if count > 0:
                if "foundation" in m_type.lower():
                    screws = count * 16
                    log.append(f"[{m_type}]")
                    log.append(f"  -> Total Screws : {screws} ({count} joints x 16)")
                    log.append("")
                else:
                    screws = count * 8
                    log.append(f"[{m_type}]")
                    log.append(f"  -> Total Screws : {screws} ({count} joints x 8)")
                    log.append("")
                
                total_screws_overall += screws
                
        boxes_needed = math.ceil(total_screws_overall / 100.0)
        
        log.append("----------------------------------------------------------------")
        log.append(f"TOTAL SCREWS REQUIRED  : {total_screws_overall}")
        log.append(f"BOXES TO BUY (100/box) : {boxes_needed} boxes ({boxes_needed * 100} screws)")
        log.append("================================================================")
        
        self.summary_text = "\n".join(log)
        return self.timber_model

    def _apply_butt_drilling(self, joint, beam1, beam2):
        cat1 = beam1.attributes.get("category", "inner")
        cat2 = beam2.attributes.get("category", "inner")
        
        is_foundation = False
        
        # Categorize the specific T-Butt Joint
        if cat1 == "base" or cat2 == "base":
            is_foundation = True
            joint_label = "TButtJoint - is foundation"
            if cat1 == "base":
                cont_beam, abut_beam = beam1, beam2
            else:
                cont_beam, abut_beam = beam2, beam1
        elif cat1 == "arch" or cat2 == "arch":
            joint_label = "TButtJoint - arch"
            if cat1 == "arch":
                cont_beam, abut_beam = beam1, beam2
            else:
                cont_beam, abut_beam = beam2, beam1
        else:
            joint_label = "TButtJoint -interior interior"
            line1, line2 = beam1.centerline, beam2.centerline
            res = intersection_line_line(line1, line2)
            if not res or res[0] is None: return False
            mid_pt = Point((res[0][0] + res[1][0]) / 2.0, (res[0][1] + res[1][1]) / 2.0, (res[0][2] + res[1][2]) / 2.0)
            d1 = min(distance_point_point(mid_pt, line1.start), distance_point_point(mid_pt, line1.end))
            d2 = min(distance_point_point(mid_pt, line2.start), distance_point_point(mid_pt, line2.end))
            if d1 < d2:
                abut_beam, cont_beam = beam1, beam2
            else:
                abut_beam, cont_beam = beam2, beam1

        line_a = abut_beam.centerline
        line_c = cont_beam.centerline
        
        res = intersection_line_line(line_a, line_c)
        if not res or res[0] is None: return False
        
        anchor_pt = Point(res[0][0], res[0][1], res[0][2])
        d_start = distance_point_point(anchor_pt, line_a.start)
        d_end = distance_point_point(anchor_pt, line_a.end)
        abut_end_pt = line_a.start if d_start < d_end else line_a.end
        
        dir_s = line_a.direction
        vec_to_mid = Vector.from_start_end(abut_end_pt, line_a.midpoint)
        if dir_s.dot(vec_to_mid) < 0:
            dir_s.scale(-1)
        dir_s.unitize()
        
        if is_foundation:
            screw_dir = Vector(0, 0, 1) 
            center_start = abut_end_pt
            center_end = center_start + (screw_dir * self.screw_length)
            
            offset_dir = screw_dir.cross(line_c.direction)
            if offset_dir.length < 1e-5:
                offset_dir = screw_dir.cross(line_a.direction)
            if offset_dir.length < 1e-5:
                offset_dir = Vector(1, 0, 0)
            offset_dir.unitize()
        else:
            screw_dir = dir_s 
            tolerance = 0.01 
            c_thickness = max(cont_beam.width, cont_beam.height)
            
            center_start = abut_end_pt - (screw_dir * (c_thickness + tolerance))
            center_end = center_start + (screw_dir * (self.screw_length + tolerance))
            
            if hasattr(abut_beam, 'frame'):
                offset_dir = Vector(abut_beam.frame.yaxis.x, abut_beam.frame.yaxis.y, abut_beam.frame.yaxis.z)
            else:
                offset_dir = dir_s.cross(line_c.direction)
            if offset_dir.length < 1e-5:
                offset_dir = Vector(0, 0, 1)
            offset_dir.unitize()

        offset_vec = offset_dir * (self.screw_spacing / 2.0)
        screw_line_1 = Line(center_start + offset_vec, center_end + offset_vec)
        screw_line_2 = Line(center_start - offset_vec, center_end - offset_vec)
        
        # Pass the custom joint_label into the features dictionary
        return self._generate_features([screw_line_1, screw_line_2], abut_beam, cont_beam, joint_label)

    def _apply_lap_drilling(self, joint, beam_a, beam_b):
        joint_label = type(joint).__name__ # e.g. XLapJoint
        line_a, line_b = beam_a.centerline, beam_b.centerline
        
        res = intersection_line_line(line_a, line_b)
        if not res or res[0] is None: return False
            
        pt_a, pt_b = res
        mid_pt = Point((pt_a[0] + pt_b[0]) / 2.0, (pt_a[1] + pt_b[1]) / 2.0, (pt_a[2] + pt_b[2]) / 2.0)
        
        dir_a, dir_b = line_a.direction, line_b.direction
        screw_dir = dir_a.cross(dir_b)
        
        if screw_dir.length < 1e-5:
            screw_dir = beam_a.frame.zaxis if hasattr(beam_a, 'frame') else Vector(0, 0, 1)
        else:
            screw_dir.unitize()
            
        offset_dir = dir_a + dir_b
        if offset_dir.length < 1e-5: offset_dir = dir_a 
        offset_dir.unitize()
        
        offset_vec = offset_dir * (self.screw_spacing / 2.0)
        center_1 = mid_pt + offset_vec
        center_2 = mid_pt - offset_vec
        
        screw_line_1 = Line(center_1 + screw_dir * (-self.screw_length / 2.0), center_1 + screw_dir * (self.screw_length / 2.0))
        screw_line_2 = Line(center_2 + screw_dir * (-self.screw_length / 2.0), center_2 + screw_dir * (self.screw_length / 2.0))
        
        return self._generate_features([screw_line_1, screw_line_2], beam_a, beam_b, joint_label)

    def _generate_features(self, screw_lines, beam_1, beam_2, joint_label): 
        success = False
        
        if joint_label not in self.screw_stats_by_type:
            self.screw_stats_by_type[joint_label] = []
            
        for s_line in screw_lines:
            line_added_to_any = False
            actual_depth = s_line.length
            
            for beam in [beam_1, beam_2]:
                try:
                    drill = Drilling.from_line_and_element(s_line, beam, diameter=self.screw_diameter)
                    
                    if self.max_drilling_depth is not None:
                        try:
                            ref_side = beam.side_as_surface(drill.ref_side_index)
                            drill.depth = drill._calculate_depth(s_line, ref_side)
                        except Exception:
                            drill.depth = s_line.length
                            
                        drill.depth_limited = True
                        if drill.depth > self.max_drilling_depth:
                            drill.depth = self.max_drilling_depth
                            
                        actual_depth = drill.depth

                    if hasattr(beam, 'add_feature'):
                        beam.add_feature(drill)
                    else:
                        beam.features.append(drill)
                    line_added_to_any = True
                except Exception:
                    pass
            
            if line_added_to_any:
                self.drilling_count += 1
                self.screw_lines.append(s_line)
                self.screw_stats_by_type[joint_label].append(actual_depth)
                success = True
            else:
                self.failed_screw_info.append({
                    "line": s_line,
                    "type": joint_label
                })
                
        return success