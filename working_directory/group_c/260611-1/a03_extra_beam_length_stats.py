# venv: ca-fs26-focus-work

from compas_rhino.devtools import DevTools
DevTools.ensure_path()
ghenv.Component.Message = "Beam Length Stats"

# ------------------------------------------------------------------ #
# Inputs (wire these in GH):
#   timber_model  –  TimberModel object from the model creator component
# ------------------------------------------------------------------ #
# Outputs:
#   stats          –  human-readable summary string
#   category_names –  list of category strings
#   lengths_total  –  total centerline length per category [m]
#   lengths_avg    –  average beam length per category [m]
#   counts         –  number of beams per category
# ------------------------------------------------------------------ #

from collections import defaultdict

cat_lengths = defaultdict(list)

for beam in timber_model.beams:
    cat = beam.attributes.get("category", "unknown")
    cat_lengths[cat].append(beam.centerline.length)

category_names = []
lengths_total = []
lengths_avg = []
counts = []

lines = ["--- BEAM LENGTH STATS ---"]

for cat in sorted(cat_lengths.keys()):
    beam_lens = cat_lengths[cat]
    n = len(beam_lens)
    total = sum(beam_lens)
    avg = total / n

    category_names.append(cat)
    lengths_total.append(total)
    lengths_avg.append(avg)
    counts.append(n)

    lines.append(
        "{:10s}  {:3d} beams  total {:7.3f} m  avg {:6.3f} m".format(
            cat, n, total, avg
        )
    )

grand_total = sum(lengths_total)
lines.append("-------------------------")
lines.append("TOTAL       {:3d} beams  total {:7.3f} m".format(
    sum(counts), grand_total
))

stats = "\n".join(lines)
print(stats)
