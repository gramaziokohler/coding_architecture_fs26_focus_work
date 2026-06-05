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
    def __init__(self, timber_model, screw_diameter=0.006, screw_length=0.150, screw_spacing=0.040):
        self.timber_model = timber_model
        self.screw_diameter = screw_diameter
        self.screw_length = screw_length
        self.screw_spacing = screw_spacing 
        self.drilling_count = 0
        self.screw_lines = []
        self.failed_screw_info = []

        
        self.total_joints_by_type = {}
        self.screwed_joints_by_type = {}

    def process_drillings(self):
        print("--- Starting Drilling Generation ---")
        
        self.total_joints_by_type = {}
        self.screwed_joints_by_type = {}
        self.drilling_count = 0
        self.failed_screw_info = []
        self.summary_text = "" # ADDED: Initialize the summary text variable
        
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
            joint_type = type(joint).__name__
            self.total_joints_by_type[joint_type] = self.total_joints_by_type.get(joint_type, 0) + 1
            
            screwed = False
            
            if isinstance(joint, TButtJoint):
                screwed = self._apply_butt_drilling(joint)
            elif isinstance(joint, (XLapJoint, TLapJoint)):
                screwed = self._apply_lap_drilling(joint)
                
            if screwed:
                self.screwed_joints_by_type[joint_type] = self.screwed_joints_by_type.get(joint_type, 0) + 1
            
        # --- COMPILE SUMMARY TEXT ---
        log = []
        log.append("================ JOINT DRILLING SUMMARY ================")
        log.append(f"Total Joints Found in Model: {len(joints)}")
        log.append("--------------------------------------------------------")
        
        total_screwed_joints = 0
        all_types = set(list(self.total_joints_by_type.keys()) + list(self.screwed_joints_by_type.keys()))
        
        for j_type in sorted(all_types):
            total_count = self.total_joints_by_type.get(j_type, 0)
            screwed_count = self.screwed_joints_by_type.get(j_type, 0)
            total_screwed_joints += screwed_count
            log.append(f" -> {j_type}: {screwed_count} of {total_count} successfully screwed")
            
        log.append("--------------------------------------------------------")
        log.append(f"Total Successfully Screwed Joints : {total_screwed_joints}")
        log.append(f"Expected Physical Screws (x2)     : {total_screwed_joints * 2}")
        log.append(f"Actual Physical Screws Placed     : {self.drilling_count}")
        
        if self.drilling_count != (total_screwed_joints * 2):
            log.append(f">>> WARNING: Missing {(total_screwed_joints * 2) - self.drilling_count} screws! Check geometry.")
            
        log.append("========================================================")
        
        # Store as a single string
        self.summary_text = "\n".join(log)
        
        return self.timber_model
    
    def _apply_butt_drilling(self, joint):
        joint_type = type(joint).__name__
        """
        Geometrically isolates the abutting beam from the continuous beam 
        to ensure proper vector alignment for the screws.
        """
        elements = getattr(joint, 'elements', [])
        if len(elements) < 2:
            return False
            
        beam1, beam2 = elements[0], elements[1]
        line1, line2 = beam1.centerline, beam2.centerline
        
        res = intersection_line_line(line1, line2)
        if not res or res[0] is None:
            return False
            
        mid_pt = Point(
            (res[0][0] + res[1][0]) / 2.0,
            (res[0][1] + res[1][1]) / 2.0,
            (res[0][2] + res[1][2]) / 2.0
        )
        
        # Geometrical Fact-Check: Identify the abutting beam by endpoint proximity
        d1 = min(distance_point_point(mid_pt, line1.start), distance_point_point(mid_pt, line1.end))
        d2 = min(distance_point_point(mid_pt, line2.start), distance_point_point(mid_pt, line2.end))
        
        if d1 < d2:
            abut_beam, cont_beam = beam1, beam2
            line_a, line_c = line1, line2
        else:
            abut_beam, cont_beam = beam2, beam1
            line_a, line_c = line2, line1
        
        # 1. Define Screw Direction (parallel to abutting beam)
        dir_s = line_a.direction
        vec_to_mid = Vector.from_start_end(mid_pt, line_a.midpoint)
        
        if dir_s.dot(vec_to_mid) < 0:
            dir_s.scale(-1)
        dir_s.unitize()

        # 2. Define Start Point (Outer face of continuous beam)
        tolerance = 0.01 
        c_thickness = max(cont_beam.width, cont_beam.height)
        start_pt = mid_pt - (dir_s * ((c_thickness / 2.0) + tolerance))

        # 3. Calculate Transverse Offset
        offset_dir = dir_s.cross(line_c.direction)
        
        if offset_dir.length < 1e-5:
            offset_dir = abut_beam.frame.zaxis if hasattr(abut_beam, 'frame') else Vector(0, 0, 1)
        else:
            offset_dir.unitize()
            
        offset_vec = offset_dir * (self.screw_spacing / 2.0)
        
        center_1 = start_pt + offset_vec
        center_2 = start_pt - offset_vec
        
        # 4. Generate Lines
        drill_len = self.screw_length + tolerance
        screw_line_1 = Line(center_1, center_1 + dir_s * drill_len)
        screw_line_2 = Line(center_2, center_2 + dir_s * drill_len)
        
        return self._generate_features([screw_line_1, screw_line_2], abut_beam, cont_beam, joint_type)

    def _apply_lap_drilling(self, joint):
        joint_type = type(joint).__name__
        elements = getattr(joint, 'elements', None)
        if not elements and hasattr(joint, 'main_beam'):
            elements = [joint.main_beam, getattr(joint, 'cross_beam')]
            
        if not elements or len(elements) < 2:
            return False
            
        beam_a, beam_b = elements[0], elements[1]
        line_a, line_b = beam_a.centerline, beam_b.centerline
        
        res = intersection_line_line(line_a, line_b)
        if not res or res[0] is None:
            return False
            
        pt_a, pt_b = res
        mid_pt = Point(
            (pt_a[0] + pt_b[0]) / 2.0,
            (pt_a[1] + pt_b[1]) / 2.0,
            (pt_a[2] + pt_b[2]) / 2.0
        )
        
        dir_a, dir_b = line_a.direction, line_b.direction
        screw_dir = dir_a.cross(dir_b)
        
        if screw_dir.length < 1e-5:
            screw_dir = beam_a.frame.zaxis if hasattr(beam_a, 'frame') else Vector(0, 0, 1)
        else:
            screw_dir.unitize()
            
        offset_dir = dir_a + dir_b
        if offset_dir.length < 1e-5:
            offset_dir = dir_a 
        offset_dir.unitize()
        
        offset_vec = offset_dir * (self.screw_spacing / 2.0)
        
        center_1 = mid_pt + offset_vec
        center_2 = mid_pt - offset_vec
        
        screw_line_1 = Line(center_1 + screw_dir * (-self.screw_length / 2.0), 
                            center_1 + screw_dir * (self.screw_length / 2.0))
        screw_line_2 = Line(center_2 + screw_dir * (-self.screw_length / 2.0), 
                            center_2 + screw_dir * (self.screw_length / 2.0))
        
        # Added joint_type argument here
        return self._generate_features([screw_line_1, screw_line_2], beam_a, beam_b, joint_type)

    def _generate_features(self, screw_lines, beam_1, beam_2, joint_type): 
        # Properly indented to belong to the DrillingProcessor class
        success = False
        
        for s_line in screw_lines:
            line_added_to_any = False
            
            for beam in [beam_1, beam_2]:
                try:
                    drill = Drilling.from_line_and_element(s_line, beam, diameter=self.screw_diameter)
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
                success = True
            else:
                self.failed_screw_info.append({
                    "line": s_line,
                    "type": joint_type
                })
                
        return success