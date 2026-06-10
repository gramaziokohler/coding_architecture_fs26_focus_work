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
    "name",
    "3d_model",
    "geometry_model",
    "blank_model",
    "frame",
    "local_frame",
    "global_position",
    "connected_beams",
    "joints",
    "processing",
    "processings",
    "features",
    "machining",
    "is_key_beam",
    "key_beam"
];

const filteredJoints = computed(() => {
    if (!beamData.value?.joints) return null;
    const skip = ["all", "details"];
    const entries = Object.entries(beamData.value.joints).filter(([key]) => !skip.includes(key));
    if (entries.length === 0) return null;
    return Object.fromEntries(entries);
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

const formatJointValue = (jointData) => {
    if (jointData === null || jointData === undefined) {
        return "—";
    }
    
    if (isArray(jointData)) {
        return jointData.length === 0 ? "—" : jointData.join(", ");
    }
    
    if (isObject(jointData)) {
        return JSON.stringify(jointData);
    }
    
    return jointData || "—";
};
</script>

<template>
    <div class="info-panel">
        <div v-if="loading" class="status">Loading...</div>
        <div v-else-if="error" class="error">Error: {{ error }}</div>
        <div v-else-if="beamData" class="beam-info">
            <!-- HEADER CON NOME E MODULE -->
            <div class="panel-header">
                <h2>{{ beamData.name }}</h2>
                <span class="module-tag">{{ beamData.module }}</span>
            </div>

            <!-- CONTENUTO SCROLLABILE -->
            <div class="scrollable-content">
                <div class="info-grid">
                    <!-- LEFT COLUMN: BEAM -->
                    <div class="info-column">
                        <h3>BEAM</h3>
                        <ul class="specs-list">
                            <li class="spec-item">
                                <span class="label">beam ID</span>
                                <span class="value">{{ beamData["beam ID"]?.toUpperCase() }}</span>
                            </li>
                            <li class="spec-item">
                                <span class="label">module</span>
                                <span class="value">{{ beamData.module }}</span>
                            </li>
                            <template v-for="(value, key) in beamData" :key="key">
                                <li
                                    v-if="!HIDDEN_KEYS.includes(key) && key !== 'beam ID' && key !== 'module' && key !== 'engraving_text'"
                                    class="spec-item"
                                >
                                    <span class="label">{{ formatLabel(key) }}</span>
                                    <span class="value">{{ formatValue(value) }}</span>
                                </li>
                            </template>
                            <li v-if="beamData.connected_beams" class="spec-item">
                                <span class="label">connected beams</span>
                                <span class="value">
                                    {{ isArray(beamData.connected_beams)
                                        ? beamData.connected_beams.map(b => b.toUpperCase()).join(", ")
                                        : beamData.connected_beams.toUpperCase() }}
                                </span>
                            </li>
                        </ul>
                    </div>

                    <!-- RIGHT COLUMN: MODULE -->
                    <div class="info-column">
                        <h3>MODULE</h3>
                        <ul class="specs-list">
                            <li class="spec-item">
                                <span class="label">engraving text</span>
                                <span class="value">{{ beamData.engraving_text || beamData.name }}</span>
                            </li>

                            <li v-if="filteredJoints" class="spec-item joints-section-title">
                                <span>joints</span>
                            </li>

                            <template v-if="filteredJoints">
                                <li
                                    v-for="(jointData, jointType) in filteredJoints"
                                    :key="jointType"
                                    class="spec-item"
                                >
                                    <span class="joint-tag">{{ jointType }}</span>
                                    <span class="joint-values">{{ formatJointValue(jointData) }}</span>
                                </li>
                            </template>

                            <li v-if="beamData.is_key_beam === true" class="spec-item">
                                <span class="label">key beams</span>
                                <span class="value">Yes</span>
                            </li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.info-panel {
    display: flex;
    flex-direction: column;
    background-color: #f5f5f5;
    border: 1px solid #ccc;
    height: 100%;
    font-family: "Helvetica Neue", Arial, sans-serif;
}

.status,
.error {
    padding: 16px;
    text-align: center;
    font-size: 14px;
    color: #666;
}

.error {
    color: #d32f2f;
}

.beam-info {
    display: flex;
    flex-direction: column;
    height: 100%;
}

.panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    background-color: #fff;
    border-bottom: 2px solid #e0e0e0;
    flex-shrink: 0;
}

h2 {
    font-size: 18px;
    font-weight: 600;
    margin: 0;
    color: #000;
}

h3 {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    color: #666;
    margin: 0 0 8px 0;
    letter-spacing: 0.5px;
}

.module-tag {
    background-color: #e8e8e8;
    padding: 6px 12px;
    border-radius: 3px;
    font-size: 12px;
    font-weight: 600;
    color: #333;
    white-space: nowrap;
}

.scrollable-content {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
}

.info-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 32px;
}

.info-column {
    display: flex;
    flex-direction: column;
}

.specs-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0;
}

.spec-item {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    padding: 6px 0;
    border-bottom: 1px solid #e0e0e0;
    font-size: 13px;
}

.spec-item:last-child {
    border-bottom: none;
}

.label {
    color: #666;
    font-weight: 400;
    flex: 0 0 auto;
    font-size: 13px;
}

.joint-tag {
    border: 1px solid #999;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
    color: #666;
    line-height: 1.4;
    flex: 0 0 auto;
}

.value,
.joint-values {
    color: #000;
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-weight: 500;
    text-align: right;
    word-break: break-word;
    flex: 1;
}

.joints-section-title {
    color: #666;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    padding: 12px 0 8px 0;
    margin-top: 8px;
    border-bottom: 2px solid #e0e0e0;
    justify-content: center;
}
</style>
