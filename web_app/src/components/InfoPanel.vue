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

onMounted(async () => {
    try {
        if (!props.beamUrl) {
            throw new Error("No beam URL provided");
        }

        console.log("InfoPanel fetching from:", props.beamUrl);

        // Construct JSON URL from beam URL
        const beamName = props.beamUrl.split("/").pop();
        const jsonUrl = props.beamUrl + "/" + beamName + ".json";

        console.log("Fetching JSON from:", jsonUrl);

        const response = await fetch(jsonUrl);
        if (!response.ok) {
            throw new Error(
                `Failed to fetch beam data: ${response.status} ${response.statusText}`,
            );
        }
        beamData.value = await response.json();
        console.log("Beam data loaded:", beamData.value);
    } catch (e) {
        error.value = e.message;
        console.error("InfoPanel error:", e);
    } finally {
        loading.value = false;
    }
});

// Helper to check if value is an object
const isObject = (value) => typeof value === "object" && value !== null;

// Helper to check if value is an array
const isArray = (value) => Array.isArray(value);

// Helper to format complex values
const formatValue = (value) => {
    if (isArray(value)) {
        return value.join(", ");
    }
    if (isObject(value)) {
        return JSON.stringify(value);
    }
    return value;
};
</script>

<template>
    <div class="info-panel">
        <div v-if="loading" class="status">Loading...</div>
        <div v-else-if="error" class="error">Error: {{ error }}</div>
        <div v-else-if="beamData" class="beam-info">
            <h2>{{ beamData.name }}</h2>
            <ul class="specs-list">
                <li
                    v-for="(value, key) in beamData"
                    :key="key"
                    v-show="!['name', '3d_model'].includes(key)"
                    class="spec-item"
                >
                    <!-- Joints - special list format -->
                    <div v-if="key === 'joints'" class="joints-item">
                        <span class="label">{{ key }}</span>
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

                    <!-- Regular values -->
                    <div v-else class="regular-item">
                        <span class="label">{{ key }}</span>
                        <span class="value">{{ formatValue(value) }}</span>
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

.error {
    color: #000;
}

.beam-info {
    width: 100%;
}

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

.spec-item:last-child {
    border-bottom: none;
}

.label {
    color: #3a28e0;
    font-weight: 400;
    text-transform: capitalize;
}

/* Regular items - same as before */
.regular-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
}

.value {
    color: #000;
    font-family: monospace;
    font-weight: 500;
    text-align: right;
    flex: 1;
    word-break: break-word;
}

/* Joints specific styling */
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
    color: rgb(201, 37, 201);
    font-family: monospace;
    font-weight: 500;
    text-align: right;
    flex: 1;
    word-break: break-word;
}
</style>
