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
        console.log("Original URL:", beam);

        // Convert GitHub web URL to raw content URL if needed
        if (beam.includes("github.com")) {
            // Handle /tree/ format (folder view)
            // Convert: https://github.com/user/repo/tree/branch/path
            // To: https://raw.githubusercontent.com/user/repo/branch/path
            beam = beam.replace(
                "https://github.com/",
                "https://raw.githubusercontent.com/",
            );
            beam = beam.replace("/tree/", "/");

            // Handle /blob/ format (file view)
            beam = beam.replace("/blob/", "/");
        }

        // Remove .json extension if present (we'll add it back later)
        if (beam.endsWith(".json")) {
            beam = beam.replace(".json", "");
        }

        beamUrl.value = beam;
        console.log("Processed Beam URL:", beamUrl.value);
    } else {
        // Default fallback
        beamUrl.value =
            "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data/beams/beam_1";
        console.log("Using default beam URL:", beamUrl.value);
    }
});
</script>

<template>
    <div class="app-container">
        <InfoPanel v-if="beamUrl" :beam-url="beamUrl" />
        <div class="viewer-container">
            <ModelViewer v-if="beamUrl" :beam-url="beamUrl" />
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
