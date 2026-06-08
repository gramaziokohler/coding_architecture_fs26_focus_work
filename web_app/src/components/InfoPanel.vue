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

            <div class="info-grid">
                <!-- LEFT: Beam -->
                <section class="info-section">
                    <h3>Beam</h3>
                    <ul class="specs-list">
                        <li
                            v-for="(value, key) in beamData"
                            :key="key"
                            v-show="!HIDDEN_KEYS.includes(key)"
                            class="spec-item"
                        >
                            <span class="label">{{ formatLabel(key) }}</span>
                            <span class="value">{{ formatValue(value) }}</span>
                        </li>
                        <li v-if="beamData.connected_beams?.length" class="spec-item">
                            <span class="label">connected beams</span>
                            <span class="value">{{ beamData.connected_beams.join(", ") }}</span>
                        </li>
                    </ul>
                </section>

                <!-- RIGHT: Module -->
                <section class="info-section">
                    <h3>Module</h3>

                    <ul class="specs-list">
                        <li class="spec-item">
                            <span class="label">engraving text</span>
                            <span class="value">{{ engravingText }}</span>
                        </li>
                    </ul>

                    <!-- Joints -->
                    <div class="joints-title-row">
                        <span class="label">joints</span>
                    </div>
                    <div v-if="filteredJoints" class="joints-container">
                        <div v-for="(items, jointType) in filteredJoints" :key="jointType" class="joint-row">
                            <span class="joint-type">{{ jointType }}</span>
                            <span class="joint-values">{{ items && items.length > 0 ? items.join(", ") : "—" }}</span>
                        </div>
                    </div>
                    <div v-else class="no-joints">—</div>
                </section>
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

h2,
h3 {
    margin: 0;
    color: #000;
    line-height: 1.2;
    font-weight: 600;
}

h2 {
    font-size: 18px;
}

h3 {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0;
    color: #555;
    margin-bottom: 6px;
}

.joints-title-row {
    margin-top: 14px;
    margin-bottom: 6px;
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

.info-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 18px;
}

.specs-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
}

.spec-item {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 6px 0;
    border-bottom: 1px solid #e0e0e0;
    font-size: 12px;
}

.spec-item:last-child {
    border-bottom: none;
}

.label {
    color: #666;
    font-weight: 400;
    flex: 0 0 auto;
    font-size: 12px;
}

.value,
.joint-values {
    color: #000;
    font-family: "Helvetica Neue", sans-serif;
    font-weight: 500;
    text-align: right;
    word-break: break-word;
}

.joints-container {
    display: flex;
    flex-direction: column;
    gap: 5px;
}

.joint-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    font-size: 12px;
    border-bottom: 1px solid #e0e0e0;
    padding-bottom: 5px;
}

.joint-type {
    color: #111;
    font-weight: 600;
    border: 1px solid #d8d8d8;
    padding: 2px 6px;
    flex: 0 0 auto;
}

.no-joints {
    font-size: 12px;
    color: #999;
}

@media (max-width: 900px) {
    .info-grid {
        grid-template-columns: 1fr;
        gap: 12px;
    }
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

    h3 {
        font-size: 10px;
        margin-bottom: 3px;
    }

    .joints-title-row {
        margin-top: 10px;
        margin-bottom: 3px;
    }

    .label {
        font-size: 10px;
    }

    .module-tag {
        padding: 2px 6px;
        font-size: 10px;
    }

    .info-grid {
        gap: 7px;
    }

    .spec-item,
    .joint-row {
        gap: 8px;
        padding: 4px 0;
        font-size: 10px;
    }

    .joint-type {
        padding: 1px 4px;
    }

    .joints-container {
        gap: 3px;
    }
}
</style>

