# Vue 3 + Vite

This template should help get you started developing with Vue 3 in Vite. The template uses Vue 3 `<script setup>` SFCs, check out the [script setup docs](https://v3.vuejs.org/api/sfc-script-setup.html#sfc-script-setup) to learn more.

Learn more about IDE Support for Vue in the [Vue Docs Scaling up Guide](https://vuejs.org/guide/scaling-up/tooling.html#ide-support).

## Regenerate `web_data` from a TimberModel

The web app does not read `timber_models/*.json` directly. It reads the split
viewer export in `web_data/`:

- `web_data/structure.json`
- `web_data/beams/<beam_id>/<beam_id>.json`
- `web_data/beams/<beam_id>/<beam_id>.stl`

To regenerate that folder from a TimberModel JSON:

```bash
python ../code/export_web_data.py ../timber_models/timber_model_friday-3.json --output ../web_data --clean
```

The exporter first looks for beam identity values in beam attributes, so Group C
can later store names/modules/numbers there without changing the rest of the
export. The fallback naming is sequential and uses:

```bash
--module-sizes A:36,B:31,C:30,D:27,E:27,F:31
```

The script writes valid STL files. At the moment those STLs are rectangular beam
solids generated from each beam `frame`, `length`, `width`, and `height`; they do
not yet include final trimmed/cut fabrication geometry.
