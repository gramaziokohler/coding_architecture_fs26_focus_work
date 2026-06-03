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

        // Construct JSON URL from beam URL
        const jsonUrl = props.beamUrl + ".json";

        const response = await fetch(jsonUrl);
        if (!response.ok) throw new Error("Failed to fetch beam data");
        beamData.value = await response.json();
    } catch (e) {
        error.value = e.message;
    } finally {
        loading.value = false;
    }
});
</script>

<template>
    <div class="info-panel">
        <div v-if="loading" class="status">Loading...</div>
        <div v-else-if="error" class="error">Error: {{ error }}</div>
        <div v-else-if="beamData" class="beam-info">
            <h2>{{ beamData.name }}</h2>
            <ul class="specs-list">
                <li class="spec-item">
                    <span class="label">ID</span>
                    <span class="value">{{ beamData.beam_id }}</span>
                </li>
                <li v-if="beamData.length" class="spec-item">
                    <span class="label">Length</span>
                    <span class="value">{{ beamData.length }} m</span>
                </li>
                <li v-if="beamData.width" class="spec-item">
                    <span class="label">Width</span>
                    <span class="value">{{ beamData.width }} m</span>
                </li>
                <li v-if="beamData.height" class="spec-item">
                    <span class="label">Height</span>
                    <span class="value">{{ beamData.height }} m</span>
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
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    padding: 8px 0;
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
}

.value {
    color: #000;
    font-family: monospace;
    font-weight: 500;
    text-align: right;
    flex: 0 0 auto;
}
</style>
