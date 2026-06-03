<script setup>
import InfoPanel from "./components/InfoPanel.vue";
import ModelViewer from "./components/ModelViewer.vue";
</script>

<template>
    <div class="app-container">
        <InfoPanel
            title="3D Model Viewer"
            description="Explore 3D models with our interactive viewer. Use your mouse to rotate and interact with the scene."
        />
        <div class="viewer-container">
            <ModelViewer />
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
