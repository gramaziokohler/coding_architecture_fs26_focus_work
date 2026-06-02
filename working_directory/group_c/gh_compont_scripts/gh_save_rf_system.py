# venv: ca-fs26-final-project

from compas_rhino.devtools import DevTools
DevTools.ensure_path()
ghenv.Component.Message = "Save RF System"

# -------------------- IMPORTS ---------------------

import pickle

# ------------------- EXECUTION --------------------

success = False
message = ""

if rf_system and filepath and run:
    try:
        # Extract just the mesh data (which can be pickled)
        is_hybrid = hasattr(rf_system, 'inner_mesh') and hasattr(rf_system, 'boundary_mesh')
        
        if is_hybrid:
            # Save hybrid system meshes
            data = {
                'type': 'hybrid',
                'inner_mesh': rf_system.inner_mesh,
                'boundary_mesh': rf_system.boundary_mesh
            }
        else:
            # Save regular RF system mesh
            data = {
                'type': 'regular',
                'mesh': rf_system.mesh
            }
        
        # Pickle the data dictionary (meshes are picklable)
        with open(filepath, 'wb') as f:
            pickle.dump(data, f, protocol=2)  # Use protocol 2 for compatibility
        
        success = True
        message = f"RF System saved to: {filepath}"
        print(message)
        
    except Exception as e:
        success = False
        message = f"Error saving RF System: {str(e)}"
        print(message)
        import traceback
        traceback.print_exc()
else:
    success = False
    message = "Please provide both rf_system and filepath and click run"
    print(message)