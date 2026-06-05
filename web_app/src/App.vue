<script setup>
import { onMounted, ref } from "vue";
import InfoPanel from "./components/InfoPanel.vue";
import ModelViewer from "./components/ModelViewer.vue";

const beamUrl = ref("");

onMounted(() => {
    const params = new URLSearchParams(window.location.search);
    let beam = params.get("beam");

    if (beam) {
        console.log("Original URL:", beam);
        if (beam.includes("github.com")) {
            beam = beam.replace("https://github.com/", "https://raw.githubusercontent.com/");
            beam = beam.replace("/tree/", "/");
            beam = beam.replace("/blob/", "/");
        }
        if (beam.endsWith(".json")) {
            beam = beam.replace(".json", "");
        }
        beamUrl.value = beam;
    } else {
        beamUrl.value = "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data/beams/beam_1";
    }
});
</script>

<template>
    <div class="app-container">
        <div class="left-panel">
            <InfoPanel v-if="beamUrl" :beam-url="beamUrl" />
        </div>
        <div class="viewer-container">
            <ModelViewer v-if="beamUrl" :beam-url="beamUrl" />
        </div>
    </div>
</template>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    padding: 0;
}

#app {
    width: 100%;
    height: 100vh;
    margin: 0;
    padding: 0;
}

.app-container {
    width: 100%;
    height: 100vh;
    display: flex;
    flex-direction: row;
}

.left-panel {
    width: 380px;
    min-width: 280px;
    height: 100vh;
    overflow-y: auto;
    border-right: 1px solid #e0e0e0;
    background: #fff;
    flex-shrink: 0;
}

.viewer-container {
    flex: 1;
    height: 100vh;
    overflow: hidden;
    background: #ffffff;
}
</style>
