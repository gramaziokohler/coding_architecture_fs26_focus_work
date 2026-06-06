<script setup>
import { computed, onMounted, ref } from "vue";
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
let structureData = null;
let gizmoRenderer, gizmoScene, gizmoCamera;

const BASE_URL = "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data";

const viewMode = ref("single");
const isLoading = ref(false);
const currentBeamId = ref("");
const currentModule = ref("");
const beamIndex = ref(-1);
const moduleIndex = ref(-1);

const WOOD_COLOR = 0xd4b896;
const HIGHLIGHT_COLOR = 0xff8fa3;
const OUTLINE_COLOR = 0x171717;
const CENTERLINE_COLOR = 0x111111;

const moduleList = computed(() => {
    if (!structureData?.beams) return [];
    return [...new Set(structureData.beams.map((beam) => beam.module))].sort();
});

const currentModuleBeams = computed(() => {
    if (!structureData?.beams || !currentModule.value) return [];
    return structureData.beams.filter((beam) => beam.module === currentModule.value);
});

const beamCounter = computed(() => {
    if (!currentModuleBeams.value.length || beamIndex.value < 0) return "";
    return `${beamIndex.value + 1} / ${currentModuleBeams.value.length}`;
});

const moduleCounter = computed(() => {
    if (!moduleList.value.length || moduleIndex.value < 0) return "";
    return `${moduleIndex.value + 1} / ${moduleList.value.length}`;
});

const loadSTL = (url) =>
    fetch(url, { mode: "cors" })
        .then((r) => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.arrayBuffer();
        })
        .then((buf) => STLLoader.prototype.parse(buf));

const loadJson = async (url) => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
};

const getBeamId = (beamData = currentBeamData) => beamData?.["beam ID"] || beamData?.beam_id || "";

const getBeamFrame = (beamData = currentBeamData) => beamData?.frame || beamData?.local_frame || null;

const getGlobalPosition = (beamData = currentBeamData) => {
    if (beamData?.global_position) return beamData.global_position;
    const frame = getBeamFrame(beamData);
    return {
        centerline_start: beamData?.centerline_start,
        centerline_end: beamData?.centerline_end,
        midpoint: beamData?.midpoint || frame?.origin,
    };
};

const vectorFromArray = (value) => new THREE.Vector3(value[0], value[1], value[2]);

const makeModelObject = (object) => {
    object.userData.isModelObject = true;
    return object;
};

const makeMesh = (geometry, color, opacity = 0.45) => {
    geometry.computeBoundingBox();
    const material = new THREE.MeshBasicMaterial({
        color,
        side: THREE.DoubleSide,
        transparent: opacity < 1,
        opacity,
        depthWrite: opacity >= 1,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.userData.isBeam = true;
    makeModelObject(mesh);
    return mesh;
};

const addOutline = (geometry) => {
    const edges = new THREE.EdgesGeometry(geometry, 18);
    const line = new THREE.LineSegments(
        edges,
        new THREE.LineBasicMaterial({
            color: OUTLINE_COLOR,
            transparent: true,
            opacity: 0.9,
        })
    );
    line.userData.isOverlay = true;
    makeModelObject(line);
    scene.add(line);
};

const clearModelObjects = () => {
    const toRemove = scene.children.filter((child) => child.userData.isModelObject);
    toRemove.forEach((child) => {
        scene.remove(child);
        if (child.geometry) child.geometry.dispose();
        if (child.material) child.material.dispose();
    });
};

const makeLine = (start, end, color, linewidth = 1) => {
    const geometry = new THREE.BufferGeometry().setFromPoints([start, end]);
    const line = new THREE.Line(
        geometry,
        new THREE.LineBasicMaterial({
            color,
            linewidth,
            transparent: true,
            opacity: 0.95,
        })
    );
    line.userData.isOverlay = true;
    makeModelObject(line);
    scene.add(line);
    return line;
};

const makeTextSprite = (text, position, color = "#111111", scale = 0.12) => {
    const canvas = document.createElement("canvas");
    canvas.width = 512;
    canvas.height = 160;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.font = "600 42px Helvetica Neue, Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "rgba(255,255,255,0.88)";
    ctx.fillRect(12, 38, 488, 84);
    ctx.strokeStyle = "rgba(17,17,17,0.25)";
    ctx.strokeRect(12, 38, 488, 84);
    ctx.fillStyle = color;
    ctx.fillText(text, 256, 82);

    const texture = new THREE.CanvasTexture(canvas);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true }));
    sprite.position.copy(position);
    sprite.scale.set(scale * 3.2, scale, 1);
    sprite.userData.isOverlay = true;
    makeModelObject(sprite);
    scene.add(sprite);
    return sprite;
};

const drawBeamFrame = (scale = 0.25) => {
    const frame = getBeamFrame();
    if (!frame?.origin || !frame?.x_axis || !frame?.y_axis || !frame?.z_axis) return;

    const origin = vectorFromArray(frame.origin);
    const headLength = scale * 0.18;
    const headWidth = scale * 0.08;
    const axes = [
        { dir: frame.x_axis, color: 0xff3030, lengthMult: 1.8, label: "X" },
        { dir: frame.y_axis, color: 0x2aa84a, lengthMult: 1.1, label: "Y" },
        { dir: frame.z_axis, color: 0x2f6fff, lengthMult: 1.1, label: "Z" },
    ];

    axes.forEach(({ dir, color, lengthMult, label }) => {
        const direction = vectorFromArray(dir).normalize();
        const length = scale * lengthMult;
        const arrow = new THREE.ArrowHelper(direction, origin, length, color, headLength, headWidth);
        arrow.userData.isOverlay = true;
        makeModelObject(arrow);
        scene.add(arrow);
        makeTextSprite(label, origin.clone().add(direction.multiplyScalar(length * 1.15)), `#${color.toString(16).padStart(6, "0")}`, scale * 0.26);
    });
};

const drawCenterline = (beamData = currentBeamData, isCurrent = true) => {
    const position = getGlobalPosition(beamData);
    if (!position?.centerline_start || !position?.centerline_end) return;
    const start = vectorFromArray(position.centerline_start);
    const end = vectorFromArray(position.centerline_end);
    makeLine(start, end, isCurrent ? CENTERLINE_COLOR : 0x777777);
};

const drawEngraving = (scale = 0.18) => {
    const position = getGlobalPosition();
    const frame = getBeamFrame();
    const labelPosition = vectorFromArray(position?.midpoint || frame?.origin || [0, 0, 0]);
    const text = currentBeamData?.engraving_text || currentBeamData?.name || getBeamId();
    if (text) makeTextSprite(text, labelPosition, "#111111", scale);
};

const drawJointLabels = (scale = 0.13) => {
    const joints = currentBeamData?.joints?.all || [];
    const position = getGlobalPosition();
    if (!joints.length || !position?.centerline_start || !position?.centerline_end) return;

    const start = vectorFromArray(position.centerline_start);
    const end = vectorFromArray(position.centerline_end);
    const direction = end.clone().sub(start);
    const normal = getBeamFrame()?.z_axis ? vectorFromArray(getBeamFrame().z_axis).normalize() : new THREE.Vector3(0, 0, 1);

    joints.forEach((jointId, index) => {
        const t = (index + 1) / (joints.length + 1);
        const point = start.clone().add(direction.clone().multiplyScalar(t)).add(normal.clone().multiplyScalar(scale * 1.5));
        makeTextSprite(`J${jointId}`, point, "#111111", scale);
    });
};

const addSelectedBeamOverlays = (sizeScale = 1) => {
    drawCenterline(currentBeamData, true);
    drawBeamFrame(sizeScale * 0.28);
    drawEngraving(sizeScale * 0.18);
    drawJointLabels(sizeScale * 0.13);
};

const centerScene = () => {
    const box = new THREE.Box3();
    scene.children
        .filter((child) => child.userData.isBeam)
        .forEach((child) => box.expandByObject(child));
    if (box.isEmpty()) return;

    const center = new THREE.Vector3();
    const size = new THREE.Vector3();
    box.getCenter(center);
    box.getSize(size);

    scene.children
        .filter((child) => child.userData.isModelObject)
        .forEach((child) => child.position.sub(center));

    const maxDim = Math.max(size.x, size.y, size.z);
    const dist = maxDim * 2.2;
    camera.position.set(0, -dist, dist * 0.65);
    camera.lookAt(0, 0, 0);
    controls.target.set(0, 0, 0);
    controls.update();
};

const loadStructure = async () => {
    if (structureData) return structureData;
    structureData = await loadJson(`${BASE_URL}/structure.json`);
    return structureData;
};

const loadBeamData = async (beamId) => loadJson(`${BASE_URL}/beams/${beamId}/${beamId}.json`);

const syncNavigationState = async () => {
    try {
        const structure = await loadStructure();
        const id = getBeamId();
        const entry = structure.beams.find((beam) => beam.beam_id === id);
        currentBeamId.value = id;
        currentModule.value = currentBeamData?.module || entry?.module || "";
        moduleIndex.value = moduleList.value.indexOf(currentModule.value);
        beamIndex.value = currentModuleBeams.value.findIndex((beam) => beam.beam_id === id);
    } catch (e) {
        console.warn("Could not load navigation structure:", e);
    }
};

const loadCurrentBeamFromUrl = async () => {
    if (!props.beamUrl) throw new Error("No beam URL");
    const beamName = props.beamUrl.split("/").pop();
    currentBeamData = await loadJson(`${props.beamUrl}/${beamName}.json`);
    await syncNavigationState();
};

const loadSingleBeam = async () => {
    clearModelObjects();
    const geometry = await loadSTL(currentBeamData["3d_model"]);
    geometry.computeBoundingBox();
    const size = new THREE.Vector3();
    geometry.boundingBox.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);

    scene.add(makeMesh(geometry, WOOD_COLOR, 0.55));
    addOutline(geometry);
    addSelectedBeamOverlays(maxDim);
    centerScene();
};

const loadConnectedBeams = async () => {
    clearModelObjects();
    const connectedIds = currentBeamData.connected_beams || [];
    const currentId = getBeamId();
    const beamIds = [currentId, ...connectedIds];

    await Promise.all(
        beamIds.map(async (id) => {
            try {
                const geometry = await loadSTL(`${BASE_URL}/beams/${id}/${id}.stl`);
                const isCurrent = id === currentId;
                scene.add(makeMesh(geometry, isCurrent ? HIGHLIGHT_COLOR : WOOD_COLOR, isCurrent ? 0.6 : 0.32));
                addOutline(geometry);
            } catch (e) {
                console.warn(`Could not load beam ${id}`, e);
            }
        })
    );

    connectedIds.forEach((id) => {
        const beam = structureData?.beams?.find((entry) => entry.beam_id === id);
        if (beam) drawCenterline(beam, false);
    });
    addSelectedBeamOverlays(1);
    centerScene();
};

const loadPavilion = async () => {
    clearModelObjects();
    const currentId = getBeamId();

    try {
        const structure = await loadStructure();
        await Promise.all(
            structure.beams.map(async (beam) => {
                const id = beam.beam_id;
                const isCurrentBeam = id === currentId;
                try {
                    const geometry = await loadSTL(`${BASE_URL}/beams/${id}/${id}.stl`);
                    scene.add(makeMesh(geometry, isCurrentBeam ? HIGHLIGHT_COLOR : WOOD_COLOR, isCurrentBeam ? 0.62 : 0.2));
                    addOutline(geometry);
                    if (isCurrentBeam) drawCenterline(currentBeamData, true);
                } catch (e) {
                    console.warn(`Could not load STL for ${id}`, e);
                }
            })
        );
        addSelectedBeamOverlays(1);
        centerScene();
    } catch (e) {
        console.warn("structure.json not found:", e);
        await loadSingleBeam();
    }
};

const setMode = async (mode) => {
    viewMode.value = mode;
    isLoading.value = true;
    try {
        if (mode === "single") await loadSingleBeam();
        else if (mode === "connected") await loadConnectedBeams();
        else if (mode === "pavilion") await loadPavilion();
    } finally {
        isLoading.value = false;
    }
};

const navigateToBeam = (beamId) => {
    if (!beamId) return;
    window.location.href = `${window.location.pathname}?beam=${encodeURIComponent(`${BASE_URL}/beams/${beamId}`)}`;
};

const navigateBeam = (step) => {
    const beams = currentModuleBeams.value;
    if (!beams.length || beamIndex.value < 0) return;
    const nextIndex = (beamIndex.value + step + beams.length) % beams.length;
    navigateToBeam(beams[nextIndex].beam_id);
};

const navigateModule = (step) => {
    const modules = moduleList.value;
    if (!modules.length || moduleIndex.value < 0) return;
    const nextModule = modules[(moduleIndex.value + step + modules.length) % modules.length];
    const beam = structureData.beams.find((entry) => entry.module === nextModule);
    navigateToBeam(beam?.beam_id);
};

const initGizmo = () => {
    const canvas = gizmoRef.value;
    gizmoRenderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    gizmoRenderer.setSize(80, 80);
    gizmoRenderer.setPixelRatio(window.devicePixelRatio);

    gizmoScene = new THREE.Scene();
    gizmoCamera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
    gizmoCamera.position.set(0, 0, 3);
    gizmoScene.add(new THREE.AxesHelper(1));
    gizmoScene.add(new THREE.AmbientLight(0xffffff, 1));
};

const updateGizmo = () => {
    if (!gizmoRenderer) return;
    gizmoCamera.position.copy(camera.position).normalize().multiplyScalar(3);
    gizmoCamera.up.copy(camera.up);
    gizmoCamera.lookAt(0, 0, 0);
    gizmoRenderer.render(gizmoScene, gizmoCamera);
};

onMounted(async () => {
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0xffffff);

    const width = containerRef.value.clientWidth;
    const height = containerRef.value.clientHeight;

    camera = new THREE.PerspectiveCamera(75, width / height, 0.01, 100000);
    camera.position.set(0, -5, 3);
    camera.up.set(0, 0, 1);
    camera.lookAt(0, 0, 0);

    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);
    containerRef.value.appendChild(renderer.domElement);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 4;
    controls.enableZoom = true;
    controls.target.set(0, 0, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 0.85));
    const dirLight = new THREE.DirectionalLight(0xffffff, 1.1);
    dirLight.position.set(5, 8, 5);
    scene.add(dirLight);

    try {
        isLoading.value = true;
        await loadCurrentBeamFromUrl();
        await loadSingleBeam();
    } catch (e) {
        console.error("Error loading beam:", e);
    } finally {
        isLoading.value = false;
    }

    initGizmo();

    const animate = () => {
        animationId = requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
        updateGizmo();
    };
    animate();

    const handleResize = () => {
        const w = containerRef.value.clientWidth;
        const h = containerRef.value.clientHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
    };
    window.addEventListener("resize", handleResize);
});
</script>

<template>
    <div ref="containerRef" class="model-viewer">
        <div class="view-buttons">
            <button :class="{ active: viewMode === 'single' }" @click="setMode('single')">Beam</button>
            <button :class="{ active: viewMode === 'connected' }" @click="setMode('connected')">Connected</button>
            <button :class="{ active: viewMode === 'pavilion' }" @click="setMode('pavilion')">Pavilion</button>
        </div>

        <div class="navigation-buttons">
            <button @click="navigateBeam(-1)">Prev Beam</button>
            <span>{{ currentBeamId }} <template v-if="beamCounter">({{ beamCounter }})</template></span>
            <button @click="navigateBeam(1)">Next Beam</button>
            <button @click="navigateModule(-1)">Prev Module</button>
            <span>Module {{ currentModule }} <template v-if="moduleCounter">({{ moduleCounter }})</template></span>
            <button @click="navigateModule(1)">Next Module</button>
        </div>

        <div class="axis-legend">
            <div class="axis-item"><span class="axis-dot" style="background: #ff3030"></span><span>beam.frame X</span></div>
            <div class="axis-item"><span class="axis-dot" style="background: #2aa84a"></span><span>beam.frame Y</span></div>
            <div class="axis-item"><span class="axis-dot" style="background: #2f6fff"></span><span>beam.frame Z</span></div>
        </div>

        <div v-if="isLoading" class="loading-overlay">
            <div class="loading-spinner"></div>
            <span>Loading...</span>
        </div>

        <canvas ref="gizmoRef" class="gizmo-canvas"></canvas>
    </div>
</template>

<style scoped>
.model-viewer {
    width: 100%;
    height: 100%;
    position: relative;
}

:deep(canvas) {
    display: block;
    touch-action: none;
}

.view-buttons,
.navigation-buttons {
    position: absolute;
    z-index: 10;
    display: flex;
    align-items: center;
    gap: 8px;
    font-family: "Helvetica Neue", sans-serif;
}

.view-buttons {
    top: 12px;
    left: 12px;
}

.navigation-buttons {
    top: 12px;
    right: 12px;
    flex-wrap: wrap;
    justify-content: flex-end;
    max-width: min(680px, calc(100% - 180px));
    color: #111;
    font-size: 12px;
}

.view-buttons button,
.navigation-buttons button {
    padding: 6px 12px;
    font-size: 12px;
    font-family: "Helvetica Neue", sans-serif;
    font-weight: 500;
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid #bdbdbd;
    border-radius: 4px;
    cursor: pointer;
}

.view-buttons button:hover,
.navigation-buttons button:hover {
    background: #f0f0f0;
}

.view-buttons button.active {
    background: #000;
    color: #fff;
    border-color: #000;
}

.navigation-buttons span {
    padding: 4px 6px;
    background: rgba(255, 255, 255, 0.75);
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

.gizmo-canvas {
    position: absolute;
    bottom: 16px;
    right: 16px;
    width: 80px;
    height: 80px;
    z-index: 10;
    pointer-events: none;
    border-radius: 4px;
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
    background: rgba(255, 255, 255, 0.85);
    padding: 20px 30px;
    border-radius: 8px;
    font-family: "Helvetica Neue", sans-serif;
    font-size: 13px;
    color: #333;
}

.loading-spinner {
    width: 28px;
    height: 28px;
    border: 3px solid #ddd;
    border-top-color: #e8643a;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
}

@media (max-width: 760px) {
    .view-buttons,
    .navigation-buttons {
        left: 10px;
        right: 10px;
        max-width: none;
    }

    .navigation-buttons {
        top: 52px;
        justify-content: flex-start;
    }
}

@keyframes spin {
    to { transform: rotate(360deg); }
}
</style>
