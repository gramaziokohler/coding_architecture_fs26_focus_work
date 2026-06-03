<script setup>
import { onMounted, ref } from "vue";
import InfoPanel from "./components/InfoPanel.vue";
import ModelViewer from "./components/ModelViewer.vue";

const beamUrl = ref("");

onMounted(() => {
    // Extract beam URL from query parameter
    const params = new URLSearchParams(window.location.search);
    let beam = params.get("beam");

    if (beam) {
        // Convert GitHub web URL to raw content URL if needed
        beam = beam.replace(
            "https://github.com/",
            "https://raw.githubusercontent.com/",
        );
        beam = beam.replace("/blob/", "/");

        // Remove .json extension if present
        if (beam.endsWith(".json")) {
            beam = beam.replace(".json", "");
        }

        beamUrl.value = beam;
        console.log("Beam URL:", beamUrl.value);
    } else {
        // Default fallback
        beamUrl.value =
            "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/web_app/web_data/beams/beam_1";
        console.log("Using default beam URL:", beamUrl.value);
    }
});
</script>

<template>
    <div class="app-container">
        <InfoPanel :beam-url="beamUrl" />
        <div class="viewer-container">
            <ModelViewer :beam-url="beamUrl" />
        </div>
    </div>
</template>

<style>
body {
    margin: 0;
    padding: 0;
}

#app {
    width: 100%;
    height: 100vh;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    border-inline: none;
    min-height: 100vh;
}

.app-container {
    width: 100%;
    height: 100vh;
    display: flex;
    flex-direction: column;
    background: var(--bg);
}

.viewer-container {
    flex: 1;
    overflow: hidden;
    background: #1a1a2e;
}
</style>
