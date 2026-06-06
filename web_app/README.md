# Vue 3 + Vite

This template should help get you started developing with Vue 3 in Vite. The template uses Vue 3 `<script setup>` SFCs, check out the [script setup docs](https://v3.vuejs.org/api/sfc-script-setup.html#sfc-script-setup) to learn more.

Learn more about IDE Support for Vue in the [Vue Docs Scaling up Guide](https://vuejs.org/guide/scaling-up/tooling.html#ide-support).

## Regenerate `web_data` from a TimberModel

The web app does not read `timber_models/*.json` directly. It reads the split
viewer export in `web_data/`:

- `web_data/structure.json`
- `web_data/beams/<beam_id>/<beam_id>.json`
- `web_data/beams/<beam_id>/<beam_id>.stl`

For final joinery geometry, use the Grasshopper component script:

```text
code/gh_compont_scripts/gh_export_web_data.py
```

It takes the live TimberModel object, runs inside Rhino, and can therefore use
`model.process_joinery()` and `beam.geometry` with Rhino's BRep backend.

To regenerate that folder from a TimberModel JSON:

```bash
python ../code/export_web_data.py ../timber_models/timber_model_friday-3.json --output ../web_data --clean
```

By default the exporter uses `--geometry-source auto`: it tries to load the
TimberModel with COMPAS Timber, runs `model.process_joinery()`, and writes STL
files from each processed `beam.geometry`. If COMPAS Timber is not available, or
if a beam geometry cannot be converted to a mesh, that beam falls back to a
rectangular STL from `frame`, `length`, `width`, and `height`.

To require real COMPAS Timber geometry and fail instead of falling back:

```bash
python ../code/export_web_data.py ../timber_models/timber_model_friday-3.json --output ../web_data --clean --geometry-source compas
```

When using the Rhino 8 Python site env on Apple Silicon, run the x86_64 Python
because the installed binary packages are x86_64:

```bash
PYTHONPATH=/Users/lorinwiedemeier/.rhinocode/py39-rh8/site-envs/ca-fs26-focus-work-p_hXDUpu \
arch -x86_64 /Users/lorinwiedemeier/.rhinocode/py39-rh8/python3.9 \
../code/export_web_data.py ../timber_models/timber_model_friday-3.json --output ../web_data --clean
```

If this prints `PluginNotInstalledError` for `Brep`, the script is running
outside a Rhino context and COMPAS cannot evaluate the final BRep geometry. In
that case the exporter still writes metadata and box fallback STLs, but final
joinery STLs need to be exported from inside Rhino/GH or from a Python runtime
with a working COMPAS BRep plugin.

The exporter first looks for beam identity values in beam attributes, so Group C
can later store names/modules/numbers there without changing the rest of the
export. The fallback naming is sequential and uses:

```bash
--module-sizes A:36,B:31,C:30,D:27,E:27,F:31
```

The script writes valid STL files. In an environment with COMPAS Timber, those
STLs should include processed joinery. Outside that environment, the STL fallback
is only the rectangular beam volume.
