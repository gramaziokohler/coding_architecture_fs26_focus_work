<script setup>
import { computed, onMounted, ref, watch } from "vue";

const props = defineProps({
    beamUrl: {
        type: String,
        default: "",
    },
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
        console.error("InfoPanel error:", e);
    } finally {
        loading.value = false;
    }
};

onMounted(loadBeamInfo);
watch(() => props.beamUrl, loadBeamInfo);

const isObject = (value) => typeof value === "object" && value !== null;
const isArray = (value) => Array.isArray(value);
const formatNumber = (value) => (Number.isFinite(value) ? Number(value).toFixed(2) : value);
const formatValue = (value) => {
    if (isArray(value)) return value.map(formatNumber).join(", ");
    if (isObject(value)) return JSON.stringify(value);
    if (Number.isFinite(value)) return Number(value).toFixed(2);
    return value;
};
const formatLabel = (key) => key.replace(/_/g, " ").replace("cm3", "cm³");

const beamRows = computed(() => {
    if (!beamData.value) return [];
    const rows = Object.entries(beamData.value)
        .filter(([key]) => !HIDDEN_KEYS.includes(key))
        .map(([key, value]) => ({ label: formatLabel(key), value: formatValue(value) }));
    if (beamData.value.connected_beams?.length) {
        rows.push({ label: "connected beams", value: beamData.value.connected_beams.join(", ") });
    }
    return rows;
});

const moduleRows = computed(() => {
    const rows = [{ label: "engraving text", value: engravingText.value }];
    if (filteredJoints.value) {
        rows.push({ label: "joints", value: "", isJointTitle: true });
        Object.entries(filteredJoints.value).forEach(([type, items]) => {
            rows.push({ label: type, value: items?.length ? items.join(", ") : "—", isJoint: true });
        });
    }
    return rows;
});

const unifiedRows = computed(() => {
    const left = beamRows.value;
    const right = moduleRows.value;
    const len = Math.max(left.length, right.length);
    return Array.from({ length: len }, (_, i) => ({
        leftLabel: left[i]?.label ?? "",
        leftValue: left[i]?.value ?? "",
        rightLabel: right[i]?.label ?? "",
        rightValue: right[i]?.value ?? "",
        rightIsJointTitle: right[i]?.isJointTitle ?? false,
        rightIsJoint: right[i]?.isJoint ?? false,
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

            <!-- Column headers -->
            <div class="unified-grid headers">
                <span class="col-header">Beam</span>
                <span></span>
                <span class="col-header">Module</span>
                <span></span>
            </div>

            <!-- Unified rows -->
            <div class="unified-grid">
                <template v-for="(row, i) in unifiedRows" :key="i">
                    <!-- Left: beam -->
                    <span class="label">{{ row.leftLabel }}</span>
                    <span class="value">{{ row.leftValue }}</span>

                    <!-- Right: module -->
                    <span
                        class="label"
                        :class="{
                            'joint-title': row.rightIsJointTitle,
                            'joint-type': row.rightIsJoint
                        }"
                    >{{ row.rightLabel }}</span>
                    <span
                        class="value"
                        :class="{ 'joint-title': row.rightIsJointTitle }"
                    >{{ row.rightIsJointTitle ? '' : row.rightValue }}</span>
                </template>
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
    color: #000;
    line-height: 1.2;
    font-weight: 600;
    font-size: 18px;
}

.module-tag {
    border: 1px solid #d0d0d0;
    padding: 3px 8px;
    font-size: 12px;
    color: #111;
}

.status,
.error {
    font-size: 13px;
    color: #666;
    padding: 4px 0;
}

.error {
    color: #000;
}

/* Grid */
.unified-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr 1fr;
}

.unified-grid.headers {
    margin-bottom: 4px;
}

.col-header {
    font-size: 12px;
    text-transform: uppercase;
    color: #555;
    font-weight: 600;
}

.unified-grid > span {
    padding: 6px 0;
    font-size: 12px;
    border-bottom: 1px solid #e0e0e0;
}

.label {
    color: #666;
    font-weight: 400;
}

.value {
    color: #000;
    font-weight: 500;
    text-align: right;
    padding-right: 24px;
    word-break: break-word;
}

/* last value of each pair no right padding */
.unified-grid > span:nth-child(4n) {
    padding-right: 0;
    text-align: right;
    color: #000;
    font-weight: 500;
}

.joint-title {
    color: #666;
    font-weight: 400;
    font-size: 12px;
}

.joint-type {
    color: #111;
    font-weight: 600;
    border: 1px solid #d8d8d8;
    padding: 2px 6px;
    align-self: center;
    display: inline-block;
    width: fit-content;
}

@media (max-width: 760px) {
    .info-panel {
        max-height: 29vh;
        padding: 8px 11px;
    }

    .panel-header {
        gap: 8px;
        margin-bottom: 6px;
    }

    h2 {
        font-size: 14px;
    }

    .col-header {
        font-size: 10px;
    }

    .module-tag {
        padding: 2px 6px;
        font-size: 10px;
    }

    .unified-grid > span {
        padding: 4px 0;
        font-size: 10px;
    }

    .joint-type {
        padding: 1px 4px;
    }
}
</style>
