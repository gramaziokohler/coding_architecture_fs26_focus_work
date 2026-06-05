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

const drawLocalFrame = (scale = 1, origin = new THREE.Vector3(0, 0, 0)) => {
    clearAxes();
    if (!currentBeamData?.local_frame) return;

    const { x_axis, y_axis, z_axis } = currentBeamData.local_frame;

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
            origin,
            arrowLength,
            color,
            headLength,
            headWidth
        );
        arrow.userData.isAxis = true;
        scene.add(arrow);
    });
};

const initScene = () => {
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0xfafafa);
    scene.fog = new THREE.Fog(0xfafafa, 500, 1000);

    camera = new THREE.PerspectiveCamera(
        50,
        containerRef.value.clientWidth / containerRef.value.clientHeight,
        0.1,
        10000
    );

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(
        containerRef.value.clientWidth,
        containerRef.value.clientHeight
    );
    renderer.shadowMap.enabled = true;
    containerRef.value.appendChild(renderer.domElement);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.autoRotate = false;

    const ambLight = new THREE.AmbientLight(0xffffff, 0.8);
    scene.add(ambLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 0.6);
    dirLight.position.set(50, 50, 50);
    dirLight.castShadow = true;
    dirLight.shadow.mapSize.width = 2048;
    dirLight.shadow.mapSize.height = 2048;
    scene.add(dirLight);

    initGizmo();
    animate();
};

const initGizmo = () => {
    gizmoRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    gizmoRenderer.setPixelRatio(window.devicePixelRatio);
    gizmoRenderer.setSize(80, 80);
    gizmoRef.value.appendChild(gizmoRenderer.domElement);

    gizmoScene = new THREE.Scene();
    gizmoScene.background = null;

    gizmoCamera = new THREE.PerspectiveCamera(50, 1, 0.1, 1000);
    gizmoCamera.position.z = 2;

    const ambLight = new THREE.AmbientLight(0xffffff, 1);
    gizmoScene.add(ambLight);

    drawGizmoAxes();
};

const drawGizmoAxes = () => {
    gizmoScene.children = [];

    if (!currentBeamData?.local_frame) {
        const defaultX = new THREE.ArrowHelper(
            new THREE.Vector3(1, 0, 0),
            new THREE.Vector3(0, 0, 0),
            1,
            0xff4444,
            0.3,
            0.2
        );
        const defaultY = new THREE.ArrowHelper(
            new THREE.Vector3(0, 1, 0),
            new THREE.Vector3(0, 0, 0),
            1,
            0x44ff44,
            0.3,
            0.2
        );
        const defaultZ = new THREE.ArrowHelper(
            new THREE.Vector3(0, 0, 1),
            new THREE.Vector3(0, 0, 0),
            1,
            0x4488ff,
            0.3,
            0.2
        );
        gizmoScene.add(defaultX, defaultY, defaultZ);
        return;
    }

    const { x_axis, y_axis, z_axis } = currentBeamData.local_frame;

    const axes = [
        { dir: x_axis, color: 0xff4444 },
        { dir: y_axis, color: 0x44ff44 },
        { dir: z_axis, color: 0x4488ff },
    ];

    axes.forEach(({ dir, color }) => {
        const direction = new THREE.Vector3(...dir).normalize();
        const arrow = new THREE.ArrowHelper(
            direction,
            new THREE.Vector3(0, 0, 0),
            1,
            color,
            0.3,
            0.2
        );
        gizmoScene.add(arrow);
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

    const mesh = makeMesh(geo, WOOD_COLOR);
    mesh.userData.isBeam = true;
    
    // Centra la mesh usando position
    const center = new THREE.Vector3();
    geo.boundingBox.getCenter(center);
    mesh.position.copy(center).negate();
    
    scene.add(mesh);

    // Usa beam.frame per l'origine reale
    const beamOrigin = currentBeamData.frame 
        ? new THREE.Vector3(...currentBeamData.frame.origin).sub(center)
        : new THREE.Vector3().sub(center);
    
    const dist = maxDim * 3.5;
    camera.position.set(0, -dist, dist * 0.6);
    camera.lookAt(0, 0, 0);
    controls.target.set(0, 0, 0);
    controls.update();

    const axisScale = maxDim * 0.6;
    drawLocalFrame(axisScale, beamOrigin);

    drawGizmoAxes();
};

const loadConnectedBeams = async () => {
    clearBeams();
    clearAxes();

    const beamIds = currentBeamData.connected_beams || [];
    const stlUrl = currentBeamData["3d_model"];
    const geo = await loadSTL(stlUrl);
    geo.computeBoundingBox();

    const size = new THREE.Vector3();
    geo.boundingBox.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);

    // Main beam
    const mainMesh = makeMesh(geo, HIGHLIGHT_COLOR);
    mainMesh.userData.isBeam = true;
    const center = new THREE.Vector3();
    geo.boundingBox.getCenter(center);
    mainMesh.position.copy(center).negate();
    scene.add(mainMesh);

    // Connected beams
    for (const id of beamIds) {
        try {
            const connGeo = await loadSTL(`${BASE_URL}/beams/${id}.stl`);
            const connMesh = makeMesh(connGeo, WOOD_COLOR, 0.7);
            connMesh.userData.isBeam = true;
            scene.add(connMesh);
        } catch (err) {
            console.warn(`Failed to load beam ${id}:`, err);
        }
    }

    const dist = maxDim * 3.5;
    camera.position.set(0, -dist, dist * 0.6);
    camera.lookAt(0, 0, 0);
    controls.target.set(0, 0, 0);
    controls.update();

    const axisScale = maxDim * 0.6;
    const beamOrigin = currentBeamData.frame 
        ? new THREE.Vector3(...currentBeamData.frame.origin).sub(center)
        : new THREE.Vector3().sub(center);
    drawLocalFrame(axisScale, beamOrigin);

    drawGizmoAxes();
};

const loadStructure = async () => {
    clearBeams();
    clearAxes();

    const allBeamsUrl = `${BASE_URL}/all_beams.json`;
    const allBeamsData = await fetch(allBeamsUrl).then((r) => r.json());

    const currentId = currentBeamData.name;
    let minBound = new THREE.Vector3(Infinity, Infinity, Infinity);
    let maxBound = new THREE.Vector3(-Infinity, -Infinity, -Infinity);

    // Load all beams
    for (const beamData of allBeamsData) {
        try {
            const stlUrl = beamData["3d_model"];
            const geo = await loadSTL(stlUrl);
            geo.computeBoundingBox();

            const color = beamData.name === currentId ? HIGHLIGHT_COLOR : WOOD_COLOR;
            const mesh = makeMesh(geo, color, beamData.name === currentId ? 1 : 0.5);
            mesh.userData.isBeam = true;
            scene.add(mesh);

            minBound.min(geo.boundingBox.min);
            maxBound.max(geo.boundingBox.max);
        } catch (err) {
            console.warn(`Failed to load beam ${beamData.name}:`, err);
        }
    }

    const center = new THREE.Vector3().addVectors(minBound, maxBound).multiplyScalar(0.5);
    const size = new THREE.Vector3().subVectors(maxBound, minBound);
    const maxDim = Math.max(size.x, size.y, size.z);

    const dist = maxDim * 2;
    camera.position.set(center.x, center.y - dist, center.z + dist * 0.6);
    camera.lookAt(center);
    controls.target.copy(center);
    controls.update();

    const axisScale = maxDim * 0.3;
    const beamOrigin = currentBeamData.frame 
        ? new THREE.Vector3(...currentBeamData.frame.origin)
        : center.clone();
    drawLocalFrame(axisScale, beamOrigin);

    drawGizmoAxes();
};

const handleViewChange = async (mode) => {
    viewMode.value = mode;
    isLoading.value = true;

    try {
        if (mode === "single") {
            await loadSingleBeam();
        } else if (mode === "connected") {
            await loadConnectedBeams();
        } else if (mode === "structure") {
            await loadStructure();
        }
    } catch (err) {
        console.error("Error loading view:", err);
    } finally {
        isLoading.value = false;
    }
};

const animate = () => {
    animationId = requestAnimationFrame(animate);

    controls.update();
    renderer.render(scene, camera);

    if (gizmoRenderer && gizmoScene && gizmoCamera) {
        gizmoRenderer.render(gizmoScene, gizmoCamera);
    }
};

const loadBeam = async () => {
    isLoading.value = true;
    try {
        const response = await fetch(props.beamUrl);
        currentBeamData = await response.json();
        viewMode.value = "single";
        await loadSingleBeam();
    } catch (error) {
        console.error("Failed to load beam:", error);
    } finally {
        isLoading.value = false;
    }
};

const handleWindowResize = () => {
    if (!containerRef.value) return;

    const width = containerRef.value.clientWidth;
    const height = containerRef.value.clientHeight;

    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);

    if (gizmoRenderer) {
        gizmoRenderer.setSize(80, 80);
    }
};

onMounted(() => {
    if (containerRef.value) {
        initScene();
        if (props.beamUrl) {
            loadBeam();
        }
        window.addEventListener("resize", handleWindowResize);
    }
});
</script>

<template>
    <div class="model-viewer" ref="containerRef">
        <div class="view-buttons">
            <button
                @click="handleViewChange('single')"
                :class="{ active: viewMode === 'single' }"
            >
                Single Beam
            </button>
            <button
                @click="handleViewChange('connected')"
                :class="{ active: viewMode === 'connected' }"
            >
                Connected Beams
            </button>
            <button
                @click="handleViewChange('structure')"
                :class="{ active: viewMode === 'structure' }"
            >
                Full Structure
            </button>
        </div>

        <div class="axis-legend">
            <div class="axis-item">
                <span class="axis-dot" style="background: #ff4444"></span>
                <span>X</span>
            </div>
            <div class="axis-item">
                <span class="axis-dot" style="background: #44ff44"></span>
                <span>Y</span>
            </div>
            <div class="axis-item">
                <span class="axis-dot" style="background: #4488ff"></span>
                <span>Z</span>
            </div>
        </div>

        <div ref="gizmoRef" class="gizmo-canvas"></div>

        <div v-if="isLoading" class="loading-overlay">
            <div class="loading-spinner"></div>
            <span>Loading...</span>
        </div>
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

.view-buttons {
    position: absolute;
    top: 12px;
    left: 12px;
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

@keyframes spin {
    to {
        transform: rotate(360deg);
    }
}
</style>
