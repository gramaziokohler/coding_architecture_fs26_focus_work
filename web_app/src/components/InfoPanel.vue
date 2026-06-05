website 

<script setup>
import { onMounted, ref } from "vue";

const props = defineProps({
    beamUrl: {
        type: String,
        default: "",
    },
});

const beamData = ref(null);
const loading = ref(true);
const error = ref(null);

// Chiavi da nascondere completamente
const HIDDEN_KEYS = ["name", "3d_model", "local_frame", "global_position", "connected_beams"];

onMounted(async () => {
    try {
        if (!props.beamUrl) {
            throw new Error("No beam URL provided");
        }
        const beamName = props.beamUrl.split("/").pop();
        const jsonUrl = props.beamUrl + "/" + beamName + ".json";
        const response = await fetch(jsonUrl);
        if (!response.ok) {
            throw new Error(`Failed to fetch beam data: ${response.status} ${response.statusText}`);
        }
        beamData.value = await response.json();
    } catch (e) {
        error.value = e.message;
        console.error("InfoPanel error:", e);
    } finally {
        loading.value = false;
    }
});

const isObject = (value) => typeof value === "object" && value !== null;
const isArray = (value) => Array.isArray(value);

const formatValue = (value) => {
    if (isArray(value)) return value.join(", ");
    if (isObject(value)) return JSON.stringify(value);
    return value;
};

// Formatta il nome della chiave: toglie underscore, capitalizza
const formatLabel = (key) => {
    return key.replace(/_/g, " ");
};
</script>

<template>
    <div class="info-panel">
        <div v-if="loading" class="status">Loading...</div>
        <div v-else-if="error" class="error">Error: {{ error }}</div>
        <div v-else-if="beamData" class="beam-info">
            <h2>{{ beamData.name }}</h2>
            <ul class="specs-list">

                <!-- Righe normali, escluse le chiavi nascoste -->
                <li
                    v-for="(value, key) in beamData"
                    :key="key"
                    v-show="!HIDDEN_KEYS.includes(key)"
                    class="spec-item"
                >
                    <!-- Joints -->
                    <div v-if="key === 'joints'" class="joints-item">
                        <span class="label">{{ formatLabel(key) }}</span>
                        <div class="joints-container">
                            <div
                                v-for="(items, jointType) in value"
                                :key="jointType"
                                class="joint-row"
                            >
                                <span class="joint-type">{{ jointType }}</span>
                                <span class="joint-values">{{
                                    items.length > 0 ? items.join(", ") : "—"
                                }}</span>
                            </div>
                        </div>
                    </div>

                    <!-- Regular -->
                    <div v-else class="regular-item">
                        <span class="label">{{ formatLabel(key) }}</span>
                        <span class="value">{{ formatValue(value) }}</span>
                    </div>
                </li>

                <!-- Riga connected beams separata, in fondo -->
                <li
                    v-if="beamData.connected_beams && beamData.connected_beams.length > 0"
                    class="spec-item"
                >
                    <div class="regular-item">
                        <span class="label">connected beams</span>
                        <span class="value">{{ beamData.connected_beams.join(", ") }}</span>
                    </div>
                </li>

            </ul>
        </div>
    </div>
</template>

<style scoped>
.info-panel {
    padding: 12px 16px;
    background: #fff;
    border-bottom: 1px solid #000;
    max-height: 40vh;
    overflow-y: auto;
}

h2 {
    margin: 0 0 8px 0;
    font-size: 18px;
    color: #000;
    line-height: 1.2;
    font-weight: 600;
}

.status,
.error {
    font-size: 13px;
    color: #666;
    padding: 4px 0;
}

.error { color: #000; }

.beam-info { width: 100%; }

.specs-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0;
}

.spec-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 8px 0;
    border-bottom: 1px solid #e0e0e0;
    font-size: 13px;
}

.spec-item:last-child { border-bottom: none; }

.label {
    color: #666;
    font-weight: 400;
}

.regular-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
}

.value {
    color: #000;
    font-family: Helvetica Neue;
    font-weight: 500;
    text-align: right;
    flex: 1;
    word-break: break-word;
}

.joints-item {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.joints-container {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-left: 12px;
    padding-left: 8px;
    border-left: 2px solid #e0e0e0;
}

.joint-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    font-size: 12px;
}

.joint-type {
    color: #666;
    font-weight: 500;
    background: #f5f5f5;
    padding: 2px 6px;
    border-radius: 3px;
    flex: 0 0 auto;
}

.joint-values {
    color: #000;
    font-family: Helvetica Neue;
    font-weight: 500;
    text-align: right;
    flex: 1;
    word-break: break-word;
}
</style>
