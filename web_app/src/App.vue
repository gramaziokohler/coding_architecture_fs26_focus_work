<script setup>
import { onMounted, ref } from "vue";
import InfoPanel from "./components/InfoPanel.vue";
import ModelViewer from "./components/ModelViewer.vue";

const beamUrl = ref("");
const isInfoPanelCollapsed = ref(false);

const setBeamUrl = (beam) => {
    if (!beam) return;
    if (beam.includes("github.com")) {
        beam = beam.replace("https://github.com/", "https://raw.githubusercontent.com/");
        beam = beam.replace("/tree/", "/");
        beam = beam.replace("/blob/", "/");
    }
    if (beam.endsWith(".json")) {
        beam = beam.replace(".json", "");
    }
    beamUrl.value = beam;
};

onMounted(() => {
    const params = new URLSearchParams(window.location.search);
    const beam = params.get("beam");

    if (beam) {
        console.log("Original URL:", beam);
        setBeamUrl(beam);
    } else {
        beamUrl.value = "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data/beams/beam_1";
    }
});
</script>

<template>
    <div class="app-container">
        <button
            v-if="beamUrl"
            class="info-toggle"
            type="button"
            :aria-expanded="(!isInfoPanelCollapsed).toString()"
            :title="isInfoPanelCollapsed ? 'Show info panel' : 'Hide info panel'"
            @click="isInfoPanelCollapsed = !isInfoPanelCollapsed"
        >
            {{ isInfoPanelCollapsed ? "Show info" : "Hide info" }}
        </button>
        <Transition name="info-slide">
            <div v-show="beamUrl && !isInfoPanelCollapsed" class="info-panel-shell">
                <InfoPanel :beam-url="beamUrl" />
            </div>
        </Transition>
        <div class="viewer-container">
            <ModelViewer v-if="beamUrl" :beam-url="beamUrl" @beam-selected="setBeamUrl" />
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
    position: relative;
    width: 100%;
    height: 100vh;
    display: flex;
    flex-direction: column;
    background: #fff;
}

.info-toggle {
    position: absolute;
    top: 10px;
    right: 132px;
    z-index: 20;
    height: 26px;
    padding: 0 8px;
    border: 1px solid #d0d0d0;
    background: #ffffff;
    color: #111111;
    font-size: 12px;
    line-height: 1;
    cursor: pointer;
}

.info-toggle:hover {
    background: #f5f5f5;
}

.info-panel-shell {
    flex: 0 0 auto;
    overflow: hidden;
}

.info-slide-enter-active,
.info-slide-leave-active {
    transition: max-height 180ms ease, opacity 160ms ease, transform 180ms ease;
}

.info-slide-enter-from,
.info-slide-leave-to {
    max-height: 0;
    opacity: 0;
    transform: translateY(-100%);
}

.info-slide-enter-to,
.info-slide-leave-from {
    max-height: 42vh;
    opacity: 1;
    transform: translateY(0);
}

.viewer-container {
    flex: 1;
    overflow: hidden;
    background: #ffffff;
    min-height: 0;
}
</style>
