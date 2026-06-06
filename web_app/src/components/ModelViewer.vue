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
const emit = defineEmits(["beam-selected"]);

const containerRef = ref(null);
const gizmoRef = ref(null);
let scene, camera, renderer, controls;
let animationId;
let currentBeamData = null;
let structureData = null;
let gizmoRenderer, gizmoScene, gizmoCamera;
let pointerDown = null;
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();

const BASE_URL = "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data";

const viewMode = ref("single");
const isLoading = ref(false);
const isAutoRotating = ref(true);
const preserveCameraOnViewChange = ref(true);
const currentBeamId = ref("");
const currentModule = ref("");
const beamIndex = ref(-1);
const moduleIndex = ref(-1);
const moduleList = ref([]);
const currentModuleBeams = ref([]);
const beamDataCache = new Map();

const WOOD_COLOR = 0xd4b896;
const HIGHLIGHT_COLOR = 0xff8fa3;
const OUTLINE_COLOR = 0x171717;
const CENTERLINE_COLOR = 0x111111;

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

const getCenterlineStart = (beamData = currentBeamData) => {
    const position = getGlobalPosition(beamData);
    return position?.centerline_start || getBeamFrame(beamData)?.origin || null;
};

const getBeamDisplayName = (beamId) => {
    if (!beamId) return "";
    const cached = beamDataCache.get(beamId);
    if (cached?.name) return cached.name;
    return beamId.toUpperCase();
};

const makeModelObject = (object) => {
    object.userData.isModelObject = true;
    return object;
};

const makeMesh = (geometry, color, opacity = 0.45, beamId = "") => {
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
    mesh.userData.beamId = beamId;
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
    ctx.font = "700 42px Helvetica Neue, Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
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

const makeTextPlane = (text, position, xAxis, yAxis, color = "#111111", scale = 0.16) => {
    const canvas = document.createElement("canvas");
    canvas.width = 512;
    canvas.height = 192;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.font = "700 64px Helvetica Neue, Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = color;
    ctx.fillText(text, 256, 96);

    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.MeshBasicMaterial({
        map: texture,
        transparent: true,
        side: THREE.DoubleSide,
        depthWrite: false,
    });
    const geometry = new THREE.PlaneGeometry(scale * 4.2, scale * 1.55);
    const plane = new THREE.Mesh(geometry, material);

    const x = xAxis.clone().normalize();
    const y = yAxis.clone().normalize();
    const z = new THREE.Vector3().crossVectors(x, y).normalize();
    const matrix = new THREE.Matrix4().makeBasis(x, y, z);
    plane.quaternion.setFromRotationMatrix(matrix);
    plane.position.copy(position);
    plane.userData.isOverlay = true;
    makeModelObject(plane);
    scene.add(plane);
    return plane;
};

const drawBeamFrame = (beamData = currentBeamData, scale = 0.25, showAxisLabels = true) => {
    const frame = getBeamFrame(beamData);
    if (!frame?.origin || !frame?.x_axis || !frame?.y_axis || !frame?.z_axis) return;

    const origin = vectorFromArray(getCenterlineStart(beamData) || frame.origin);
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
        if (showAxisLabels) {
            makeTextSprite(label, origin.clone().add(direction.multiplyScalar(length * 1.15)), `#${color.toString(16).padStart(6, "0")}`, scale * 0.26);
        }
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
    const text = currentBeamData?.engraving_text || currentBeamData?.label_text || currentBeamData?.name || getBeamId();
    if (!text || !frame) return;

    const engraving = currentBeamData?.engraving || currentBeamData?.label || currentBeamData?.beam_label || {};
    const origin = vectorFromArray(
        engraving.position ||
        engraving.location ||
        engraving.origin ||
        position?.midpoint ||
        frame.origin ||
        [0, 0, 0]
    );
    const xAxis = vectorFromArray(engraving.x_axis || frame.x_axis);
    const yAxis = vectorFromArray(engraving.y_axis || frame.y_axis);
    const normal = vectorFromArray(engraving.normal || frame.z_axis).normalize();
    const faceOffset = Number.isFinite(engraving.offset) ? engraving.offset : 0.004;
    makeTextPlane(text, origin.add(normal.multiplyScalar(faceOffset)), xAxis, yAxis, "#111111", scale);
};

const closestPointsOnSegments = (p1, q1, p2, q2) => {
    const d1 = q1.clone().sub(p1);
    const d2 = q2.clone().sub(p2);
    const r = p1.clone().sub(p2);
    const a = d1.dot(d1);
    const e = d2.dot(d2);
    const f = d2.dot(r);
    const epsilon = 1e-9;
    let s = 0;
    let t = 0;

    if (a <= epsilon && e <= epsilon) {
        return [p1.clone(), p2.clone()];
    }
    if (a <= epsilon) {
        t = THREE.MathUtils.clamp(f / e, 0, 1);
    } else {
        const c = d1.dot(r);
        if (e <= epsilon) {
            s = THREE.MathUtils.clamp(-c / a, 0, 1);
        } else {
            const b = d1.dot(d2);
            const denom = a * e - b * b;
            if (denom !== 0) {
                s = THREE.MathUtils.clamp((b * f - c * e) / denom, 0, 1);
            }
            t = (b * s + f) / e;
            if (t < 0) {
                t = 0;
                s = THREE.MathUtils.clamp(-c / a, 0, 1);
            } else if (t > 1) {
                t = 1;
                s = THREE.MathUtils.clamp((b - c) / a, 0, 1);
            }
        }
    }

    return [
        p1.clone().add(d1.multiplyScalar(s)),
        p2.clone().add(d2.multiplyScalar(t)),
    ];
};

const jointTypeById = (jointId) => {
    const groups = currentBeamData?.joints || {};
    return Object.entries(groups).find(([key, ids]) => key !== "all" && Array.isArray(ids) && ids.includes(jointId))?.[0] || "";
};

const exportedJointRecords = () => {
    const records =
        currentBeamData?.joint_details ||
        currentBeamData?.joint_info ||
        currentBeamData?.joint_locations ||
        currentBeamData?.joints?.details ||
        [];
    return Array.isArray(records) ? records : [];
};

const buildJointRecords = () => {
    const exported = exportedJointRecords().map((joint) => {
        const connectedBeamId = joint.connected_beam || joint.connected_beam_id || joint.other_beam || joint.other_beam_id || joint.beam_b;
        return {
            id: String(joint.id || joint.joint_id || joint.name || ""),
            connectedBeamId,
            label: joint.label || `${getBeamDisplayName(getBeamId())} to ${getBeamDisplayName(connectedBeamId)}`,
            location: joint.location || joint.position || joint.point,
            type: joint.type || joint.joint_type,
        };
    });
    if (exported.length) return exported;

    const joints = currentBeamData?.joints?.all || [];
    const connectedIds = currentBeamData?.connected_beams || [];
    return joints.map((jointId, index) => ({
        id: String(jointId),
        connectedBeamId: connectedIds[index],
        label: `${getBeamDisplayName(getBeamId())} to ${getBeamDisplayName(connectedIds[index])}`,
        type: jointTypeById(jointId),
    }));
};

const fallbackJointLocation = (connectedBeamId, index, count) => {
    const position = getGlobalPosition();
    if (!position?.centerline_start || !position?.centerline_end) return null;

    const start = vectorFromArray(position.centerline_start);
    const end = vectorFromArray(position.centerline_end);
    const connectedBeam = beamDataCache.get(connectedBeamId) || structureData?.beams?.find((beam) => beam.beam_id === connectedBeamId);
    const connectedPosition = connectedBeam ? getGlobalPosition(connectedBeam) : null;

    if (connectedPosition?.centerline_start && connectedPosition?.centerline_end) {
        const connectedStart = vectorFromArray(connectedPosition.centerline_start);
        const connectedEnd = vectorFromArray(connectedPosition.centerline_end);
        const [pointA, pointB] = closestPointsOnSegments(start, end, connectedStart, connectedEnd);
        return pointA.add(pointB).multiplyScalar(0.5);
    }

    const t = (index + 1) / (count + 1);
    return start.clone().lerp(end, t);
};

const drawJointLabels = (scale = 0.13) => {
    const records = buildJointRecords();
    if (!records.length) return;

    const normal = getBeamFrame()?.z_axis ? vectorFromArray(getBeamFrame().z_axis).normalize() : new THREE.Vector3(0, 0, 1);

    records.forEach((joint, index) => {
        const location = joint.location ? vectorFromArray(joint.location) : fallbackJointLocation(joint.connectedBeamId, index, records.length);
        if (!location) return;
        const label = joint.label || `${getBeamDisplayName(getBeamId())} to ${getBeamDisplayName(joint.connectedBeamId)}`;
        const point = location.add(normal.clone().multiplyScalar(scale * 0.9));
        makeTextSprite(label, point, "#111111", scale);
    });
};

const addSelectedBeamOverlays = (sizeScale = 1) => {
    drawCenterline(currentBeamData, true);
    drawBeamFrame(currentBeamData, sizeScale * 0.28, true);
    drawEngraving(sizeScale * 0.18);
    drawJointLabels(sizeScale * 0.13);
};

const centerScene = ({ preserveCamera = false } = {}) => {
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

    if (preserveCamera) {
        controls.update();
        return;
    }

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

const loadBeamData = async (beamId) => {
    if (beamDataCache.has(beamId)) return beamDataCache.get(beamId);
    const beamData = await loadJson(`${BASE_URL}/beams/${beamId}/${beamId}.json`);
    beamDataCache.set(beamId, beamData);
    return beamData;
};

const syncNavigationState = async () => {
    try {
        const structure = await loadStructure();
        const id = getBeamId();
        const entry = structure.beams.find((beam) => beam.beam_id === id);
        currentBeamId.value = id;
        currentModule.value = currentBeamData?.module || entry?.module || "";
        moduleList.value = [...new Set(structure.beams.map((beam) => beam.module))].sort();
        currentModuleBeams.value = structure.beams.filter((beam) => beam.module === currentModule.value);
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
    beamDataCache.set(getBeamId(currentBeamData), currentBeamData);
    await syncNavigationState();
};

const loadSingleBeam = async ({ preserveCamera = false } = {}) => {
    clearModelObjects();
    const geometry = await loadSTL(currentBeamData["3d_model"]);
    geometry.computeBoundingBox();
    const size = new THREE.Vector3();
    geometry.boundingBox.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);

    scene.add(makeMesh(geometry, WOOD_COLOR, 0.55, getBeamId()));
    addOutline(geometry);
    addSelectedBeamOverlays(maxDim);
    centerScene({ preserveCamera });
};

const loadConnectedBeams = async ({ preserveCamera = false } = {}) => {
    clearModelObjects();
    const connectedIds = currentBeamData.connected_beams || [];
    const currentId = getBeamId();
    const beamIds = [currentId, ...connectedIds];

    await Promise.all(
        beamIds.map(async (id) => {
            try {
                const [geometry, beamData] = await Promise.all([
                    loadSTL(`${BASE_URL}/beams/${id}/${id}.stl`),
                    loadBeamData(id),
                ]);
                const isCurrent = id === currentId;
                scene.add(makeMesh(geometry, isCurrent ? HIGHLIGHT_COLOR : WOOD_COLOR, isCurrent ? 0.6 : 0.32, id));
                addOutline(geometry);
                if (!isCurrent) {
                    drawBeamFrame(beamData, 0.08, false);
                }
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
    centerScene({ preserveCamera });
};

const loadPavilion = async ({ preserveCamera = false } = {}) => {
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
                    scene.add(makeMesh(geometry, isCurrentBeam ? HIGHLIGHT_COLOR : WOOD_COLOR, isCurrentBeam ? 0.62 : 0.2, id));
                    addOutline(geometry);
                    if (isCurrentBeam) drawCenterline(currentBeamData, true);
                } catch (e) {
                    console.warn(`Could not load STL for ${id}`, e);
                }
            })
        );
        addSelectedBeamOverlays(1);
        centerScene({ preserveCamera });
    } catch (e) {
        console.warn("structure.json not found:", e);
        await loadSingleBeam({ preserveCamera });
    }
};

const setMode = async (mode, { preserveCamera = preserveCameraOnViewChange.value } = {}) => {
    viewMode.value = mode;
    isLoading.value = true;
    try {
        if (mode === "single") await loadSingleBeam({ preserveCamera });
        else if (mode === "connected") await loadConnectedBeams({ preserveCamera });
        else if (mode === "pavilion") await loadPavilion({ preserveCamera });
    } finally {
        isLoading.value = false;
    }
};

const setAutoRotate = () => {
    if (controls) {
        controls.autoRotate = isAutoRotating.value;
    }
};

const selectBeam = async (beamId) => {
    if (!beamId || beamId === getBeamId()) return;
    isLoading.value = true;
    try {
        currentBeamData = await loadBeamData(beamId);
        await syncNavigationState();
        const nextBeamUrl = `${BASE_URL}/beams/${beamId}`;
        const query = new URLSearchParams(window.location.search);
        query.set("beam", nextBeamUrl);
        window.history.pushState({}, "", `${window.location.pathname}?${query.toString()}`);
        emit("beam-selected", nextBeamUrl);
        await setMode(viewMode.value, { preserveCamera: preserveCameraOnViewChange.value });
    } catch (e) {
        console.error(`Could not select beam ${beamId}:`, e);
    } finally {
        isLoading.value = false;
    }
};

const navigateToBeam = (beamId) => {
    selectBeam(beamId);
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

const beamFromPointerEvent = (event) => {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const beamMeshes = scene.children.filter((child) => child.userData.isBeam);
    const hits = raycaster.intersectObjects(beamMeshes, false);
    return hits[0]?.object?.userData?.beamId || "";
};

const handlePointerDown = (event) => {
    pointerDown = {
        x: event.clientX,
        y: event.clientY,
        time: performance.now(),
    };
};

const handlePointerUp = (event) => {
    if (!pointerDown) return;
    const dx = event.clientX - pointerDown.x;
    const dy = event.clientY - pointerDown.y;
    const distance = Math.hypot(dx, dy);
    const duration = performance.now() - pointerDown.time;
    pointerDown = null;

    if (distance > 6 || duration > 500) return;
    const beamId = beamFromPointerEvent(event);
    if (beamId) selectBeam(beamId);
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
    renderer.domElement.addEventListener("pointerdown", handlePointerDown);
    renderer.domElement.addEventListener("pointerup", handlePointerUp);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.autoRotate = isAutoRotating.value;
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
            <label class="rotate-toggle">
                <input v-model="isAutoRotating" type="checkbox" @change="setAutoRotate" />
                Auto rotate
            </label>
            <label class="rotate-toggle">
                <input v-model="preserveCameraOnViewChange" type="checkbox" />
                Keep camera
            </label>
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
.navigation-buttons button,
.rotate-toggle {
    padding: 6px 12px;
    font-size: 12px;
    font-family: "Helvetica Neue", sans-serif;
    font-weight: 500;
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid #bdbdbd;
    border-radius: 4px;
}

.view-buttons button,
.navigation-buttons button {
    cursor: pointer;
}

.view-buttons button:hover,
.navigation-buttons button:hover,
.rotate-toggle:hover {
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

.rotate-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: #111;
    cursor: pointer;
    user-select: none;
}

.rotate-toggle input {
    margin: 0;
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
