<script setup>
import { computed, onMounted, ref, watch } from "vue";

const props = defineProps({
    beamUrl: { type: String, default: "" },
});

const beamData = ref(null);
const loading = ref(true);
const error = ref(null);

const HIDDEN_KEYS = [
    "name", "3d_model", "frame", "local_frame", "global_position",
    "connected_beams", "joints", "processing", "processings", "features", "machining"
];

const engravingText = computed(() =>
    beamData.value?.engraving_text || beamData.value?.name || beamData.value?.["beam ID"]
);

const filteredJoints = computed(() => {
    if (!beamData.value?.joints) return null;
    const skip = ["all", "details"];
    return Object.fromEntries(
        Object.entries(beamData.value.joints).filter(([key]) => !skip.includes(key))
    );
});

const loadBeamInfo = async () => {
    loading.value = true;
    error.value = null;
    try {
        if (!props.beamUrl) throw new Error("No beam URL provided");
        const beamName = props.beamUrl.split("/").pop();
        const jsonUrl = props.beamUrl + "/" + beamName + ".json";
        const response = await fetch(jsonUrl);
        if (!response.ok) throw new Error(`Failed to fetch beam data: ${response.status} ${response.statusText}`);
        beamData.value = await response.json();
    } catch (e) {
        error.value = e.message;
    } finally {
        loading.value = false;
    }
};

onMounted(loadBeamInfo);
watch(() => props.beamUrl, loadBeamInfo);

const isArray = (value) => Array.isArray(value);
const isObject = (value) => typeof value === "object" && value !== null;
const formatNumber = (value) => (Number.isFinite(value) ? Number(value).toFixed(2) : value);
const formatValue = (value) => {
    if (isArray(value)) return value.map(formatNumber).join(", ");
    if (isObject(value)) return JSON.stringify(value);
    if (Number.isFinite(value)) return Number(value).toFixed(2);
    return value;
};
const formatLabel = (key) => key.replace(/_/g, " ").replace("cm3", "cm³");

// Righe colonna sinistra (beam)
const leftRows = computed(() => {
    if (!beamData.value) return [];
    const rows = [];
    for (const [key, value] of Object.entries(beamData.value)) {
        if (!HIDDEN_KEYS.includes(key)) {
            rows.push({ label: formatLabel(key), value: formatValue(value) });
        }
    }
    if (beamData.value.connected_beams?.length) {
        rows.push({ label: "connected beams", value: beamData.value.connected_beams.join(", ") });
    }
    return rows;
});

// Righe colonna destra (module)
const rightRows = computed(() => {
    const rows = [];
    rows.push({ label: "engraving text", value: engravingText.value, type: "normal" });
    rows.push({ label: "joints", value: "", type: "title" });
    if (filteredJoints.value) {
        for (const [type, items] of Object.entries(filteredJoints.value)) {
            rows.push({ label: type, value: items?.length ? items.join(", ") : "—", type: "joint" });
        }
    }
    return rows;
});

// Merge in righe unificate
const rows = computed(() => {
    const len = Math.max(leftRows.value.length, rightRows.value.length);
    return Array.from({ length: len }, (_, i) => ({
        left: leftRows.value[i] || null,
        right: rightRows.value[i] || null,
    }));
});
</script>

<template>
    <div class="info-panel">
        <div v-if="loading" class="status">Loading...</div>
        <div v-else-if="error" class="error">Error: {{ error }}</div>
        <div v-else-if="beamData" class="beam-info">

            <div class="panel-header">
                <h2>{{ beamData.name }}</h2>
                <span class="module-tag">Module {{ beamData.module }}</span>
            </div>

            <!-- Headers -->
            <div class="row headers-row">
                <span class="col-label"></span>
                <span class="col-value header-text">Beam</span>
                <span class="col-label header-text">Module</span>
                <span class="col-value"></span>
            </div>

            <!-- Righe unificate -->
            <div
                v-for="(row, i) in rows"
                :key="i"
                class="row"
            >
                <!-- Sinistra -->
                <span class="col-label left-label">{{ row.left?.label ?? '' }}</span>
                <span class="col-value left-value">{{ row.left?.value ?? '' }}</span>

                <!-- Destra -->
                <span
                    class="col-label right-label"
                    :class="{
                        'joint-title': row.right?.type === 'title',
                        'joint-tag': row.right?.type === 'joint',
                    }"
                >{{ row.right?.label ?? '' }}</span>
                <span class="col-value right-value">
                    {{ row.right?.type === 'title' ? '' : (row.right?.value ?? '') }}
                </span>
            </div>

        </div>
    </div>
</template>

<style scoped>
.info-panel {
    padding: 12px 16px;
    background: #fff;
    border-bottom: 1px solid #000;
    max-height: 42vh;
    overflow-y: auto;
}

.panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 10px;
}

h2 {
    margin: 0;
    font-weight: 600;
    font-size: 18px;
}

.module-tag {
    border: 1px solid #d0d0d0;
    padding: 3px 8px;
    font-size: 12px;
}

/* Ogni riga è una griglia a 4 colonne */
.row {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr 1fr;
    height: 32px;
    align-items: center;
    border-bottom: 1px solid #e0e0e0;
    font-size: 12px;
}

.headers-row {
    border-bottom: 2px solid #ccc;
    margin-bottom: 0;
}

.header-text {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    color: #555;
}

.col-label {
    color: #666;
}

.col-value {
    text-align: right;
    font-weight: 500;
    color: #000;
    padding-right: 24px;
}

/* ultima colonna niente padding */
.row > span:last-child {
    padding-right: 0;
}

.joint-title {
    color: #666;
    font-weight: 400;
}

.joint-tag {
    display: inline-flex;
    align-items: center;
    border: 1px solid #d8d8d8;
    padding: 2px 6px;
    font-weight: 600;
    width: fit-content;
    height: 22px;
    font-size: 12px;
}

.status, .error {
    font-size: 13px;
    color: #666;
}

@media (max-width: 760px) {
    .info-panel { max-height: 29vh; padding: 8px 11px; }
    h2 { font-size: 14px; }
    .row { height: 24px; font-size: 10px; }
    .header-text { font-size: 10px; }
    .joint-tag { height: 18px; font-size: 10px; padding: 1px 4px; }
}
</style>
