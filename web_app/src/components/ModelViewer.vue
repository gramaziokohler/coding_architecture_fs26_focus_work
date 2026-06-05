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

// ─── STL loader helper ───────────────────────────────────────────────
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

// ─── Clear all beam meshes ────────────────────────────────────────────
const clearBeams = () => {
    const toRemove = scene.children.filter((c) => c.userData.isBeam);
    toRemove.forEach((c) => scene.remove(c));
};

// ─── Clear axis arrows ────────────────────────────────────────────────
const clearAxes = () => {
    const toRemove = scene.children.filter((c) => c.userData.isAxis);
    toRemove.forEach((c) => scene.remove(c));
};

// ─── Draw local frame axes ────────────────────────────────────────────
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

// ─── Center scene around loaded meshes ───────────────────────────────
const centerScene = () => {
    const box = new THREE.Box3();
    scene.children
        .filter((c) => c.userData.isBeam)
        .forEach((c) => box.expandByObject(c));
    if (box.isEmpty()) return;

    const center = new THREE.Vector3();
    box.getCenter(center);
    scene.children
        .filter((c) => c.userData.isBeam)
        .forEach((c) => c.position.sub(center));

    const size = new THREE.Vector3();
    box.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);

    controls.target.set(0, 0, 0);
    camera.position.set(maxDim * 1.5, maxDim * 1.5, maxDim * 1.5);
    camera.lookAt(0, 0, 0);
    controls.update();
};

// ─── Load single beam ─────────────────────────────────────────────────
const loadSingleBeam = async () => {
    clearBeams();
    clearAxes();
    const stlUrl = currentBeamData["3d_model"];
    const geo = await loadSTL(stlUrl);
    geo.computeBoundingBox();
    const center = new THREE.Vector3();
    geo.boundingBox.getCenter(center);
    geo.translate(-center.x, -center.y, -center.z);
    const size = new THREE.Vector3();
    geo.boundingBox.getSize(size);
    const scale = 2 / Math.max(size.x, size.y, size.z);
    const mesh = makeMesh(geo, WOOD_COLOR);
    mesh.scale.multiplyScalar(scale);
    mesh.userData.isBeam = true;
    scene.add(mesh);
    controls.target.set(0, 0, 0);
    camera.lookAt(0, 0, 0);
    controls.update();

    const axisScale = 1.2 * scale * Math.max(size.x, size.y, size.z) * 0.5;
    drawLocalFrame(axisScale);
};

// ─── Load connected beams ─────────────────────────────────────────────
const loadConnectedBeams = async () => {
    clearBeams();
    clearAxes();
    const connectedIds = currentBeamData.connected_beams || [];

    try {
        const geo = await loadSTL(currentBeamData["3d_model"]);
        const mesh = makeMesh(geo, HIGHLIGHT_COLOR);
        mesh.userData.isBeam = true;
        scene.add(mesh);
    } catch (e) {
        console.error("Error loading main beam", e);
    }

    for (const id of connectedIds) {
        try {
            const stlUrl = `${BASE_URL}/beams/${id}/${id}.stl`;
            const geo = await loadSTL(stlUrl);
            const mesh = makeMesh(geo, WOOD_COLOR);
            mesh.userData.isBeam = true;
            scene.add(mesh);
        } catch (e) {
            console.warn(`Could not load beam ${id}`, e);
        }
    }

    centerScene();
};

// ─── Load full pavilion ───────────────────────────────────────────────
const loadPavilion = async () => {
    clearBeams();
    clearAxes();
    const currentId = currentBeamData["beam ID"];

    try {
        const structureUrl = `${BASE_URL}/structure.json`;
        const res = await fetch(structureUrl);
        if (!res.ok) throw new Error("No structure.json");
        const structure = await res.json();

        const loadPromises = structure.beams.map(async (beam) => {
            const id = beam.beam_id;
            const isCurrentBeam = id === currentId;
            const color = isCurrentBeam ? HIGHLIGHT_COLOR : WOOD_COLOR;

            try {
                const stlUrl = `${BASE_URL}/beams/${id}/${id}.stl`;
                const geo = await loadSTL(stlUrl);
                const mesh = makeMesh(geo, color);
                mesh.userData.isBeam = true;
                scene.add(mesh);
            } catch (e) {
                console.warn(`Could not load STL for ${id}`, e);
            }
        });

        await Promise.all(loadPromises);
        centerScene();
    } catch (e) {
        console.warn("structure.json not found:", e);
        await loadSingleBeam();
    }
};

// ─── View mode buttons ────────────────────────────────────────────────
const setMode = async (mode) => {
    viewMode.value = mode;
    isLoading.value = true;
    clearAxes();
    try {
        if (mode === "single") await loadSingleBeam();
        else if (mode === "connected") await loadConnectedBeams();
        else if (mode === "pavilion") await loadPavilion();
    } finally {
        isLoading.value = false;
    }
};

// ─── Gizmo setup ─────────────────────────────────────────────────────
const initGizmo = () => {
    const canvas = gizmoRef.value;
    gizmoRenderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    gizmoRenderer.setSize(80, 80);
    gizmoRenderer.setPixelRatio(window.devicePixelRatio);

    gizmoScene = new THREE.Scene();
    gizmoCamera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
    gizmoCamera.position.set(0, 0, 3);

    const axesHelper = new THREE.AxesHelper(1);
    gizmoScene.add(axesHelper);

    const makeLabel = (text, pos, color) => {
        const canvas2 = document.createElement("canvas");
        canvas2.width = 64;
        canvas2.height = 64;
        const ctx = canvas2.getContext("2d");
        ctx.fillStyle = color;
        ctx.font = "bold 40px Arial";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(text, 32, 32);
        const tex = new THREE.CanvasTexture(canvas2);
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex }));
        sprite.position.copy(pos);
        sprite.scale.set(0.4, 0.4, 1);
        gizmoScene.add(sprite);
    };
    makeLabel("X", new THREE.Vector3(1.4, 0, 0), "#ff4444");
    makeLabel("Y", new THREE.Vector3(0, 1.4, 0), "#44ff44");
    makeLabel("Z", new THREE.Vector3(0, 0, 1.4), "#4488ff");

    gizmoScene.add(new THREE.AmbientLight(0xffffff, 1));
};

const updateGizmo = () => {
    if (!gizmoRenderer) return;
    gizmoCamera.position.copy(camera.position).normalize().multiplyScalar(3);
    gizmoCamera.lookAt(0, 0, 0);
    gizmoCamera.up.copy(camera.up);
    gizmoRenderer.render(gizmoScene, gizmoCamera);
};

// ─── Mount ────────────────────────────────────────────────────────────
onMounted(async () => {
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0xffffff);

    const width = containerRef.value.clientWidth;
    const height = containerRef.value.clientHeight;

    camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);
    camera.position.set(3, 3, 2);
    camera.up.set(0, 0, 1);

    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    containerRef.value.appendChild(renderer.domElement);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 4;
    controls.enableZoom = true;
    controls.target.set(0, 0, 0);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
    dirLight.position.set(5, 8, 5);
    dirLight.castShadow = true;
    scene.add(dirLight);
    scene.add(new THREE.AmbientLight(0xffffff, 0.8));
    const fillLight = new THREE.DirectionalLight(0xffffff, 0.4);
    fillLight.position.set(-5, 3, -5);
    scene.add(fillLight);

    try {
        if (!props.beamUrl) throw new Error("No beam URL");
        const beamName = props.beamUrl.split("/").pop();
        const jsonUrl = `${props.beamUrl}/${beamName}.json`;
        const response = await fetch(jsonUrl);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        currentBeamData = await response.json();
        isLoading.value = true;
        await loadSingleBeam();
        isLoading.value = false;
    } catch (e) {
        console.error("Error loading beam:", e);
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

    return () => {
        window.removeEventListener("resize", handleResize);
        cancelAnimationFrame(animationId);
        controls.dispose();
        renderer.dispose();
    };
});
</script>

<template>
    <div ref="containerRef" class="model-viewer">
        <div class="view-buttons">
            <button
                :class="{ active: viewMode === 'single' }"
                @click="setMode('single')"
            >Beam</button>
            <button
                :class="{ active: viewMode === 'connected' }"
                @click="setMode('connected')"
            >Connected</button>
            <button
                :class="{ active: viewMode === 'pavilion' }"
                @click="setMode('pavilion')"
            >Pavilion</button>
        </div>

        <div v-if="viewMode === 'single'" class="axis-legend">
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
    to { transform: rotate(360deg); }
}
</style>
