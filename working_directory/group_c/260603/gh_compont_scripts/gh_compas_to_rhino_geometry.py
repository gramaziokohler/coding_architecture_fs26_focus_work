# venv: ca-fs26-final-project

"""
Convert COMPAS geometry to Rhino geometry.
Filters out None values (deleted/invalid elements).
"""

from typing import Any

import Grasshopper

from compas.scene import SceneObject


class CompasToRhinoGeometry(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, cg):
        if not cg:
            return None

        # Handle lists - filter out None values
        if isinstance(cg, list):
            filtered = [item for item in cg if item is not None]
            if not filtered:
                return None
            
            # Convert each valid item
            result = []
            for item in filtered:
                try:
                    rhino_geom = SceneObject(item=item).draw()
                    if rhino_geom is not None:
                        result.append(rhino_geom)
                except Exception as e:
                    print(f"Warning: Could not convert item to Rhino geometry: {e}")
            
            return result if result else None
        
        # Handle single item
        if cg is None:
            return None
        
        try:
            return SceneObject(item=cg).draw()
        except Exception as e:
            print(f"Warning: Could not convert to Rhino geometry: {e}")
            return None