<script setup>
import { onMounted, ref } from "vue";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

const props = defineProps({
    beamUrl: {
        type: String,
        default: "",
    },
});

const containerRef = ref(null);
const gizmoRef = ref(null);
let scene, camera, renderer, controls;
let animationId;
let currentBeamData = null;
let gizmoRenderer, gizmoScene, gizmoCamera;

const BASE_URL = "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data";

const viewMode = ref("single");
const isLoading = ref(false);

const WOOD_COLOR = 0xd4b896;
const HIGHLIGHT_COLOR = 0xff8fa3;

const loadSTL = (url) =>
    fetch(url, { mode: "cors" })
        .then((r) => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.arrayBuffer();
        })
        .then((buf) => STLLoader.prototype.parse(buf));

const makeMesh = (geometry, color, opacity = 1) => {
    geometry.computeBoundingBox();
    const mat = new THREE.MeshBasicMaterial({
        color,
        side: THREE.DoubleSide,
        transparent: opacity < 1,
        opacity,
    });
    const mesh = new THREE.Mesh(geometry, mat);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
};

const clearBeams = () => {
    const toRemove = scene.children.filter((c) => c.userData.isBeam);
    toRemove.forEach((c) => scene.remove(c));
};

const clearAxes = () => {
    const toRemove = scene.children.filter((c) => c.userData.isAxis);
    toRemove.forEach((c) => scene.remove(c));
};

const drawLocalFrame = (scale = 1) => {
    clearAxes();
    if (!currentBeamData?.local_frame) return;

    const { x_axis, y_axis, z_axis } = currentBeamData.local_frame;
    const o = new THREE.Vector3(0, 0, 0);

    const headLength = scale * 0.15;
    const headWidth = scale * 0.08;

    const axes = [
        { dir: x_axis, color: 0xff4444, lengthMult: 1.6 },
        { dir: y_axis, color: 0x44ff44, lengthMult: 1.0 },
        { dir: z_axis, color: 0x4488ff, lengthMult: 1.0 },
    ];

    axes.forEach(({ dir, color, lengthMult }) => {
        const direction = new THREE.Vector3(...dir).normalize();
        const arrowLength = scale * lengthMult;
        const arrow = new THREE.ArrowHelper(
            direction,
            o,
            arrowLength,
            color,
            headLength,
            headWidth
        );
        arrow.userData.isAxis = true;
        scene.add(arrow);
    });
};

const loadSingleBeam = async () => {
    clearBeams();
    clearAxes();
    const stlUrl = currentBeamData["3d_model"];
    const geo = await loadSTL(stlUrl);
    geo.computeBoundingBox();

    const size = new THREE.Vector3();
    geo.boundingBox.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);

    // TRASLA LA GEOMETRIA PER ALLINEAMENTO CORRETTO
    const minPoint = geo.boundingBox.min.clone();
    const center = geo.boundingBox.getCenter(new THREE.Vector3());

    geo.translate(
        -minPoint.x,  // Sposta inizio a X=0
        -center.y,     // Centra sezione in Y
        -center.z      // Centra sezione in Z
    );
    geo.computeBoundingBox();

    const mesh = makeMesh(geo, WOOD_COLOR);
    mesh.userData.isBeam = true;
    mesh.position.set(0, 0, 0);

    scene.add(mesh);

    const dist = maxDim * 3.5;
    camera.position.set(0, -dist, dist * 0.6);
    camera.lookAt(0, 0, 0);
    controls.target.set(0, 0, 0);
    controls.update();

    const axisScale = maxDim * 0.6;
    drawLocalFrame(axisScale);
};

const loadConnectedBeams = async () => {
    clearBeams();
    clearAxes();

    const stlUrl = currentBeamData["3d_model"];
    const geo = await loadSTL(stlUrl);
    geo.computeBoundingBox();

    const size = new THREE.Vector3();
    geo.boundingBox.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);

    // Trasla anche il beam principale
    const minPoint = geo.boundingBox.min.clone();
    const center = geo.boundingBox.getCenter(new THREE.Vector3());

    geo.translate(
        -minPoint.x,
        -center.y,
        -center.z
    );
    geo.computeBoundingBox();

    const mesh = makeMesh(geo, WOOD_COLOR);
    mesh.userData.isBeam = true;
    mesh.position.set(0, 0, 0);
    scene.add(mesh);

    const connectedBeams = currentBeamData.connected_beams || [];
    let maxDimOverall = maxDim;

    for (const beamId of connectedBeams) {
        try {
            const response = await fetch(`${BASE_URL}/beams/${beamId}.json`);
            if (!response.ok) continue;
            const beamData = await response.json();

            const connGeo = await loadSTL(beamData["3d_model"]);
            connGeo.computeBoundingBox();

            const connSize = new THREE.Vector3();
            connGeo.boundingBox.getSize(connSize);
            maxDimOverall = Math.max(maxDimOverall, ...Object.values(connSize));

            // Trasla anche i beam connessi
            const connMinPoint = connGeo.boundingBox.min.clone();
            const connCenter = connGeo.boundingBox.getCenter(new THREE.Vector3());

            connGeo.translate(
                -connMinPoint.x,
                -connCenter.y,
                -connCenter.z
            );
            connGeo.computeBoundingBox();

            const connMesh = makeMesh(connGeo, HIGHLIGHT_COLOR, 0.7);
            connMesh.userData.isBeam = true;

            // Posiziona il beam connesso usando il suo global_position
            if (beamData.global_position) {
                const pos = beamData.global_position;
                connMesh.position.set(pos[0], pos[1], pos[2]);
            }

            scene.add(connMesh);
        } catch (e) {
            console.error(`Errore caricamento beam ${beamId}:`, e);
        }
    }

    const dist = maxDimOverall * 3.5;
    camera.position.set(0, -dist, dist * 0.6);
    camera.lookAt(0, 0, 0);
    controls.target.set(0, 0, 0);
    controls.update();

    const axisScale = maxDimOverall * 0.6;
    drawLocalFrame(axisScale);
};

const loadBeamData = async (url) => {
    if (!url) return;
    isLoading.value = true;

    try {
        let beamUrl = url;
        if (beamUrl.includes("github.com")) {
            beamUrl = beamUrl.replace("https://github.com/", "https://raw.githubusercontent.com/");
            beamUrl = beamUrl.replace("/tree/", "/");
            beamUrl = beamUrl.replace("/blob/", "/");
        }
        if (!beamUrl.endsWith(".json")) {
            beamUrl += ".json";
        }

        const response = await fetch(beamUrl);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        currentBeamData = await response.json();

        if (viewMode.value === "single") {
            await loadSingleBeam();
        } else {
            await loadConnectedBeams();
        }
    } catch (error) {
        console.error("Errore nel caricamento:", error);
    } finally {
        isLoading.value = false;
    }
};

const initScene = () => {
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0xfafafa);

    camera = new THREE.PerspectiveCamera(
        50,
        containerRef.value.clientWidth / containerRef.value.clientHeight,
        0.1,
        10000
    );

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(containerRef.value.clientWidth, containerRef.value.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    containerRef.value.appendChild(renderer.domElement);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 2;

    const animate = () => {
        animationId = requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
    };
    animate();

    window.addEventListener("resize", onWindowResize);
};

const onWindowResize = () => {
    const width = containerRef.value.clientWidth;
    const height = containerRef.value.clientHeight;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
};

const switchViewMode = async (newMode) => {
    viewMode.value = newMode;
    if (currentBeamData) {
        if (newMode === "single") {
            await loadSingleBeam();
        } else {
            await loadConnectedBeams();
        }
    }
};

onMounted(() => {
    initScene();

    let beamUrl = props.beamUrl;
    if (beamUrl) {
        if (beamUrl.includes("github.com")) {
            beamUrl = beamUrl.replace("https://github.com/", "https://raw.githubusercontent.com/");
            beamUrl = beamUrl.replace("/tree/", "/");
            beamUrl = beamUrl.replace("/blob/", "/");
        }
        if (beamUrl.endsWith(".json")) {
            beamUrl = beamUrl.replace(".json", "");
        }
    } else {
        beamUrl = "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data/beams/beam_1";
    }

    loadBeamData(beamUrl);
});
</script>

<template>
    <div class="model-viewer-container">
        <div ref="containerRef" class="viewer"></div>

        <div v-if="isLoading" class="loading-overlay">
            <div class="loading-spinner"></div>
            <span>Caricamento modello...</span>
        </div>

        <div class="view-buttons">
            <button
                :class="{ active: viewMode === 'single' }"
                @click="switchViewMode('single')"
            >
                Singola Trave
            </button>
            <button
                :class="{ active: viewMode === 'connected' }"
                @click="switchViewMode('connected')"
            >
                Travi Connesse
            </button>
        </div>

        <div class="axis-legend">
            <div class="axis-item">
                <div class="axis-dot" style="background-color: #ff4444;"></div>
                <span>X-Axis</span>
            </div>
            <div class="axis-item">
                <div class="axis-dot" style="background-color: #44ff44;"></div>
                <span>Y-Axis</span>
            </div>
            <div class="axis-item">
                <div class="axis-dot" style="background-color: #4488ff;"></div>
                <span>Z-Axis</span>
            </div>
        </div>

        <div class="beam-info">
            <h3 v-if="currentBeamData" class="beam-title">
                {{ currentBeamData.name || "Beam Info" }}
            </h3>
            <ul v-if="currentBeamData" class="spec-list">
                <li class="spec-item">
                    <div class="regular-item">
                        <span class="label">ID</span>
                        <span class="value">{{ currentBeamData.id }}</span>
                    </div>
                </li>

                <li class="spec-item">
                    <div class="regular-item">
                        <span class="label">Length</span>
                        <span class="value">{{ currentBeamData.length?.toFixed(2) }} mm</span>
                    </div>
                </li>

                <li class="spec-item">
                    <div class="regular-item">
                        <span class="label">Volume</span>
                        <span class="value">{{ currentBeamData.volume?.toFixed(2) }} mm³</span>
                    </div>
                </li>

                <li class="spec-item">
                    <div class="regular-item">
                        <span class="label">Material</span>
                        <span class="value">{{ currentBeamData.material || "Unknown" }}</span>
                    </div>
                </li>

                <li v-if="currentBeamData.joints && currentBeamData.joints.length > 0" class="spec-item">
                    <div class="joints-item">
                        <span class="label">Joints</span>
                        <div class="joints-container">
                            <div v-for="(joint, idx) in currentBeamData.joints" :key="idx" class="joint-row">
                                <span class="joint-type">{{ joint.type }}</span>
                                <span class="joint-values">
                                    {{ joint.elements?.join(", ") || "N/A" }}
                                </span>
                            </div>
                        </div>
                    </div>
                </li>

                <li v-if="currentBeamData.connected_beams && currentBeamData.connected_beams.length > 0" class="spec-item">
                    <div class="regular-item">
                        <span class="label">Connected Beams</span>
                        <span class="value">{{ currentBeamData.connected_beams.join(", ") }}</span>
                    </div>
                </li>
            </ul>
        </div>
    </div>
</template>

<style scoped>
.model-viewer-container {
    position: relative;
    width: 100%;
    height: 100vh;
    overflow: hidden;
    background: #fafafa;
}

.viewer {
    width: 100%;
    height: 100%;
}

.beam-info {
    position: absolute;
    top: 16px;
    right: 16px;
    z-index: 10;
    background: rgba(255, 255, 255, 0.95);
    border: 1px solid #ddd;
    border-radius: 6px;
    padding: 16px;
    max-width: 300px;
    max-height: 70vh;
    overflow-y: auto;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    font-family: "Helvetica Neue", sans-serif;
}

.beam-title {
    margin: 0 0 12px 0;
    font-size: 14px;
    font-weight: 600;
    color: #000;
}

.spec-list {
    list-style: none;
    padding: 0;
    margin: 0;
}

.spec-item {
    padding: 8px 0;
    border-bottom: 1px solid #e8e8e8;
}

.spec-item:last-child {
    border-bottom: none;
}

.label {
    color: #666;
    font-weight: 400;
    font-size: 12px;
}

.regular-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
}

.value {
    color: #000;
    font-family: "Helvetica Neue", sans-serif;
    font-weight: 500;
    text-align: right;
    flex: 1;
    word-break: break-word;
    font-size: 12px;
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
    font-size: 11px;
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
    font-family: "Helvetica Neue", sans-serif;
    font-weight: 500;
    text-align: right;
    flex: 1;
    word-break: break-word;
    font-size: 11px;
}

.view-buttons {
    position: absolute;
    bottom: 16px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 10;
    display: flex;
    gap: 8px;
}

.view-buttons button {
    padding: 6px 14px;
    font-size: 12px;
    font-family: "Helvetica Neue", sans-serif;
    font-weight: 500;
    background: rgba(255, 255, 255, 0.9);
    border: 1px solid #ccc;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.15s;
}

.view-buttons button:hover {
    background: #f0f0f0;
}

.view-buttons button.active {
    background: #000;
    color: #fff;
    border-color: #000;
}

.axis-legend {
    position: absolute;
    bottom: 16px;
    left: 16px;
    z-index: 10;
    background: rgba(255, 255, 255, 0.85);
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 6px 10px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-family: "Helvetica Neue", sans-serif;
    font-size: 11px;
    color: #333;
}

.axis-item {
    display: flex;
    align-items: center;
    gap: 6px;
}

.axis-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
}

.loading-overlay {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    z-index: 20;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    background: rgba(255, 255, 255, 0.95);
    padding: 20px 30px;
    border-radius: 8px;
    font-family: "Helvetica Neue", sans-serif;
    font-size: 13px;
    color: #333;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.loading-spinner {
    width: 28px;
    height: 28px;
    border: 3px solid #ddd;
    border-top-color: #e8643a;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
}

@keyframes spin {
    to {
        transform: rotate(360deg);
    }
}
</style>
