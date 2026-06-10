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
let gizmoScene, gizmoCamera, gizmoRenderer;
let animationId;
let structureData = null;
let currentBeamData = null;
let pointerDown = null;

const beamDataCache = new Map();
const beamDataCacheVersion = ref(0);

const BASE_URL = "https://example.com/data";
const WOOD_COLOR = 0x8b7355;
const HIGHLIGHT_COLOR = 0xff6b6b;
const MODULE_COLOR = 0x4ecdc4;
const KEY_BEAM_COLOR = 0xffe066;

const MODULE_PALETTE = [
    0xff6b6b, 0x4ecdc4, 0x45b7d1, 0xf9ca24, 0x6c5ce7,
    0xa29bfe, 0xfd79a8, 0xfdcb6e, 0x6c7a89, 0x00b894,
];

const viewMode = ref("single");
const isLoading = ref(false);
const currentBeamId = ref("");
const currentModule = ref("");
const moduleList = ref([]);
const currentModuleBeams = ref([]);
const moduleIndex = ref(-1);
const beamIndex = ref(-1);
const shownBeamIds = ref([]);
const isAutoRotating = ref(false);
const preserveCameraOnViewChange = ref(false);
const autoOrientBeamFrame = ref(false);
const colorCurrentModule = ref(false);
const colorAllModules = ref(false);
const showKeyBeams = ref(false);
const hoverInfo = ref(null);
const hoverStyle = ref({});

const pointer = new THREE.Vector2();
const raycaster = new THREE.Raycaster();

const getBeamId = (beam = currentBeamData) => {
    return beam?.beam_id || beam?.id || "";
};

const getDisplayFrame = (beam = currentBeamData) => {
    return beam?.beam_frame || beam?.frame;
};

const mobileOverlayScale = () => {
    return window.innerWidth < 800 ? 0.55 : 1;
};

const beamCounter = computed(() => {
    if (viewMode.value === "single") return null;
    const total = shownBeamIds.value.length;
    const index = shownBeamIds.value.indexOf(getBeamId()) + 1;
    return total > 0 ? `${index}/${total}` : null;
});

const moduleCounter = computed(() => {
    return moduleList.value.length > 0 ? `${moduleIndex.value + 1}/${moduleList.value.length}` : null;
});

const totalShownWeight = computed(() => {
    return shownBeamIds.value.reduce((sum, id) => {
        const cached = beamDataCache.get(id);
        return sum + (cached?.weight || 0);
    }, 0).toFixed(2);
});

const loadJson = async (url) => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Failed to load ${url}`);
    return response.json();
};

const loadSTL = async (url) => {
    return new Promise((resolve, reject) => {
        const loader = new STLLoader();
        loader.load(
            url,
            (geometry) => resolve(geometry),
            undefined,
            (error) => reject(error)
        );
    });
};

const makeMesh = (geometry, color, opacity, beamId) => {
    const material = new THREE.MeshPhongMaterial({
        color,
        side: THREE.DoubleSide,
        transparent: opacity < 1,
        opacity,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.userData.isBeam = true;
    mesh.userData.beamId = beamId;
    return mesh;
};

const addOutline = (geometry) => {
    const edges = new THREE.EdgesGeometry(geometry);
    const line = new THREE.LineSegments(
        edges,
        new THREE.LineBasicMaterial({ color: 0x999999, linewidth: 1 })
    );
    scene.add(line);
};

const drawCenterline = (beamData, isSelected = false) => {
    if (!beamData || !getDisplayFrame(beamData)) return;
    const frame = getDisplayFrame(beamData);
    const start = new THREE.Vector3(...(frame.origin || [0, 0, 0]));
    const direction = new THREE.Vector3(...(frame.y_axis || [0, 1, 0])).normalize();
    const length = beamData.length || 1;
    const end = start.clone().add(direction.clone().multiplyScalar(length));

    const points = [start, end];
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const color = isSelected ? 0xff0000 : 0x999999;
    const material = new THREE.LineBasicMaterial({ color, linewidth: 2 });
    const line = new THREE.Line(geometry, material);
    line.userData.isModelObject = true;
    scene.add(line);
};

const drawBeamFrame = (beamData, scale = 0.1, isSelected = false) => {
    if (!beamData || !getDisplayFrame(beamData)) return;
    const frame = getDisplayFrame(beamData);
    const origin = new THREE.Vector3(...(frame.origin || [0, 0, 0]));

    const axes = [
        { axis: frame.x_axis, color: 0xff3030 },
        { axis: frame.y_axis, color: 0x2aa84a },
        { axis: frame.z_axis, color: 0x2f6fff },
    ];

    axes.forEach(({ axis, color }) => {
        const direction = new THREE.Vector3(...axis).normalize().multiplyScalar(scale);
        const end = origin.clone().add(direction);
        const points = [origin, end];
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const material = new THREE.LineBasicMaterial({ color, linewidth: 2 });
        const line = new THREE.Line(geometry, material);
        line.userData.isModelObject = true;
        scene.add(line);
    });
};

const drawEngraving = (scale = 0.05) => {
    if (!currentBeamData?.engraving_position) return;
    const pos = currentBeamData.engraving_position;
    const point = new THREE.Vector3(...pos);
    const geometry = new THREE.SphereGeometry(scale, 8, 8);
    const material = new THREE.MeshBasicMaterial({ color: 0xff00ff });
    const sphere = new THREE.Mesh(geometry, material);
    sphere.position.copy(point);
    sphere.userData.isModelObject = true;
    sphere.userData.hoverInfo = {
        title: "Engraving",
        lines: [`Position: ${pos.map((v) => v.toFixed(2)).join(", ")}`],
    };
    scene.add(sphere);
};

const drawCameraBeamLabel = (beamData, scale = 0.07) => {
    if (!beamData) return;
    const frame = getDisplayFrame(beamData);
    if (!frame) return;
    const pos = new THREE.Vector3(...(frame.origin || [0, 0, 0]));
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 128;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "white";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "black";
    ctx.font = "bold 32px Arial";
    ctx.textAlign = "center";
    ctx.fillText(getBeamId(beamData), canvas.width / 2, canvas.height / 2);

    const texture = new THREE.CanvasTexture(canvas);
    const geometry = new THREE.PlaneGeometry(1, 0.5);
    const material = new THREE.MeshBasicMaterial({ map: texture, side: THREE.DoubleSide });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.copy(pos);
    mesh.scale.multiplyScalar(scale);
    mesh.userData.isModelObject = true;
    scene.add(mesh);
};

const drawJointLabels = (scale = 0.038) => {
    if (!currentBeamData?.joints) return;
    currentBeamData.joints.forEach((joint, index) => {
        const pos = new THREE.Vector3(...(joint.position || [0, 0, 0]));
        const canvas = document.createElement("canvas");
        canvas.width = 128;
        canvas.height = 64;
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "white";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "black";
        ctx.font = "bold 16px Arial";
        ctx.textAlign = "center";
        ctx.fillText(`J${index}`, canvas.width / 2, canvas.height / 2);

        const texture = new THREE.CanvasTexture(canvas);
        const geometry = new THREE.PlaneGeometry(1, 0.5);
        const material = new THREE.MeshBasicMaterial({ map: texture, side: THREE.DoubleSide });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.position.copy(pos);
        mesh.scale.multiplyScalar(scale);
        mesh.userData.isModelObject = true;
        scene.add(mesh);
    });
};

const drawProcessing = () => {
    if (!currentBeamData?.processing) return;
    currentBeamData.processing.forEach((proc) => {
        if (!proc.position) return;
        const pos = new THREE.Vector3(...proc.position);
        const geometry = new THREE.BoxGeometry(0.02, 0.02, 0.02);
        const material = new THREE.MeshBasicMaterial({ color: 0x00ff00 });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.position.copy(pos);
        mesh.userData.isModelObject = true;
        mesh.userData.hoverInfo = {
            title: proc.type || "Processing",
            lines: [`Position: ${proc.position.map((v) => v.toFixed(2)).join(", ")}`],
        };
        scene.add(mesh);
    });
};

const clearModelObjects = () => {
    const toRemove = scene.children.filter((child) => child.userData.isModelObject);
    toRemove.forEach((child) => scene.remove(child));
};

const addSelectedBeamOverlays = (sizeScale = 1) => {
    const responsiveScale = sizeScale * mobileOverlayScale();
    drawCenterline(currentBeamData, true);
    drawBeamFrame(currentBeamData, responsiveScale * 0.168, true);
    drawEngraving(responsiveScale * 0.045);
    drawCameraBeamLabel(currentBeamData, responsiveScale * 0.07);
    drawJointLabels(responsiveScale * 0.038);
    drawProcessing();
};

const shouldEmphasizeModuleBeam = (beamData) => {
    return colorCurrentModule.value && beamData?.module === currentModule.value;
};

const addModuleBeamLabel = (beamData, scale = 0.055) => {
    if (!shouldEmphasizeModuleBeam(beamData) || getBeamId(beamData) === getBeamId()) return;
    drawCameraBeamLabel(beamData, scale);
};

const moduleColor = (moduleName) => {
    const index = moduleList.value.indexOf(moduleName);
    if (index >= 0) return MODULE_PALETTE[index % MODULE_PALETTE.length];

    let hash = 0;
    String(moduleName || "").split("").forEach((char) => {
        hash = (hash * 31 + char.charCodeAt(0)) % MODULE_PALETTE.length;
    });
    return MODULE_PALETTE[hash];
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
    camera.up.set(0, 0, 1);
    camera.position.set(0, -dist, dist * 0.65);
    camera.lookAt(0, 0, 0);
    controls.target.set(0, 0, 0);
    controls.update();
};

const orientCameraToBeamFrame = (distanceHint = 1) => {
    const frame = getDisplayFrame();
    if (!frame || !controls) return;

    const target = controls.target.clone();
    const up = frame.z_axis.clone().normalize();
    let viewDirection = frame.y_axis.clone().normalize();

    viewDirection.sub(up.clone().multiplyScalar(viewDirection.dot(up)));
    if (viewDirection.lengthSq() < 1e-8) {
        viewDirection = new THREE.Vector3().crossVectors(frame.x_axis, up).normalize();
    } else {
        viewDirection.normalize();
    }

    const currentDirection = camera.position.clone().sub(target).normalize();
    if (viewDirection.dot(currentDirection) < 0) {
        viewDirection.negate();
    }

    const distance = Math.max(camera.position.distanceTo(target), distanceHint * 2.2, 0.1);
    camera.up.copy(up);
    camera.position.copy(target).add(viewDirection.multiplyScalar(distance));
    camera.lookAt(target);
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
    beamDataCacheVersion.value += 1;
    return beamData;
};

const resolveModelUrl = (modelPath) => {
    if (!modelPath) return "";
    if (modelPath.startsWith("http://") || modelPath.startsWith("https://")) {
        return modelPath;
    }
    return `${BASE_URL}/${modelPath.replace(/^\/+/, "")}`;
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
    beamDataCacheVersion.value += 1;
    await syncNavigationState();
};

const loadSingleBeam = async ({ preserveCamera = false } = {}) => {
    clearModelObjects();
    shownBeamIds.value = [getBeamId()];
    const geometry = await loadSTL(resolveModelUrl(currentBeamData["3d_model"]));
    geometry.computeBoundingBox();
    const size = new THREE.Vector3();
    geometry.boundingBox.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);

    scene.add(makeMesh(geometry, WOOD_COLOR, 0.55, getBeamId()));
    addOutline(geometry);
    addSelectedBeamOverlays(maxDim);
    centerScene({ preserveCamera: preserveCamera && !autoOrientBeamFrame.value });
    if (autoOrientBeamFrame.value) orientCameraToBeamFrame(maxDim);
};

const loadConnectedBeams = async ({ preserveCamera = false } = {}) => {
    clearModelObjects();
    const connectedIds = currentBeamData.connected_beams || [];
    const currentId = getBeamId();
    const beamIds = [currentId, ...connectedIds];
    shownBeamIds.value = beamIds;

    await Promise.all(
        beamIds.map(async (id) => {
            try {
                const [geometry, beamData] = await Promise.all([
                    loadSTL(`${BASE_URL}/beams/${id}/${id}.stl`),
                    loadBeamData(id),
                ]);
                const isCurrent = id === currentId;
                const isCurrentModule = shouldEmphasizeModuleBeam(beamData);
                const color = isCurrent ? HIGHLIGHT_COLOR : (isCurrentModule ? MODULE_COLOR : WOOD_COLOR);
                const opacity = isCurrent ? 0.6 : (isCurrentModule ? 0.42 : 0.32);
                scene.add(makeMesh(geometry, color, opacity, id));
                addOutline(geometry);
                if (!isCurrent) {
                    drawBeamFrame(beamData, 0.08, false);
                    addModuleBeamLabel(beamData, 0.05);
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
    centerScene({ preserveCamera: preserveCamera && !autoOrientBeamFrame.value });
    if (autoOrientBeamFrame.value) orientCameraToBeamFrame();
};

const loadModuleBeams = async ({ preserveCamera = false } = {}) => {
    clearModelObjects();
    const currentId = getBeamId();

    try {
        const structure = await loadStructure();
        const moduleBeams = structure.beams.filter((beam) => beam.module === currentModule.value);
        shownBeamIds.value = moduleBeams.map((beam) => beam.beam_id);

        await Promise.all(
            moduleBeams.map(async (beam) => {
                const id = beam.beam_id;
                const isCurrentBeam = id === currentId;
                try {
                    const [geometry, beamData] = await Promise.all([
                        loadSTL(`${BASE_URL}/beams/${id}/${id}.stl`),
                        loadBeamData(id),
                    ]);
                    const color = isCurrentBeam ? HIGHLIGHT_COLOR : (colorCurrentModule.value ? MODULE_COLOR : WOOD_COLOR);
                    const opacity = isCurrentBeam ? 0.62 : (colorCurrentModule.value ? 0.42 : 0.28);
                    scene.add(makeMesh(geometry, color, opacity, id));
                    addOutline(geometry);
                    drawCenterline(beamData, isCurrentBeam);
                    if (!isCurrentBeam) {
                        drawBeamFrame(beamData, 0.08, false);
                        addModuleBeamLabel(beamData, 0.052);
                    }
                } catch (e) {
                    console.warn(`Could not load module beam ${id}`, e);
                }
            })
        );
        addSelectedBeamOverlays(1);
        centerScene({ preserveCamera: preserveCamera && !autoOrientBeamFrame.value });
        if (autoOrientBeamFrame.value) orientCameraToBeamFrame();
    } catch (e) {
        console.warn("Could not load module beams:", e);
        await loadConnectedBeams({ preserveCamera });
    }
};

const loadPavilion = async ({ preserveCamera = false } = {}) => {
    clearModelObjects();
    const currentId = getBeamId();

    try {
        const structure = await loadStructure();
        shownBeamIds.value = structure.beams.map((beam) => beam.beam_id);
        await Promise.all(
            structure.beams.map(async (beam) => {
                const id = beam.beam_id;
                const isCurrentBeam = id === currentId;
                const isCurrentModule = colorCurrentModule.value && beam.module === currentModule.value;
                try {
                    const [geometry, beamData] = await Promise.all([
                        loadSTL(`${BASE_URL}/beams/${id}/${id}.stl`),
                        loadBeamData(id),
                    ]);
                    const isKeyBeam = beamData?.is_key_beam === true || beamData?.key_beam === true;
                    const color = isCurrentBeam ? HIGHLIGHT_COLOR 
                        : (showKeyBeams.value && isKeyBeam ? KEY_BEAM_COLOR 
                        : (isCurrentModule ? MODULE_COLOR 
                        : (colorAllModules.value ? moduleColor(beam.module) : WOOD_COLOR)));
                    const opacity = isCurrentBeam ? 0.62 
                        : (showKeyBeams.value && isKeyBeam ? 0.72 
                        : ((isCurrentModule || colorAllModules.value) ? 0.36 : 0.18));
                    scene.add(makeMesh(geometry, color, opacity, id));
                    addOutline(geometry);
                    if (isCurrentBeam) drawCenterline(currentBeamData, true);
                    else if (beamData) addModuleBeamLabel(beamData, 0.045);
                } catch (e) {
                    console.warn(`Could not load STL for ${id}`, e);
                }
            })
        );
        addSelectedBeamOverlays(1);
        centerScene({ preserveCamera: preserveCamera && !autoOrientBeamFrame.value });
        if (autoOrientBeamFrame.value) orientCameraToBeamFrame();
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
        else if (mode === "module") await loadModuleBeams({ preserveCamera });
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

const hoverFromPointerEvent = (event) => {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);

    const hoverables = scene.children.filter((child) => child.userData.hoverInfo);
    const hits = raycaster.intersectObjects(hoverables, false);
    const hit = hits[0]?.object;
    if (!hit) {
        hoverInfo.value = null;
        return;
    }

    hoverInfo.value = hit.userData.hoverInfo;
    hoverStyle.value = {
        left: `${event.clientX + 12}px`,
        top: `${event.clientY + 12}px`,
    };
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

const handlePointerMove = (event) => {
    hoverFromPointerEvent(event);
};

const handlePointerLeave = () => {
    hoverInfo.value = null;
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
    renderer.domElement.addEventListener("pointermove", handlePointerMove);
    renderer.domElement.addEventListener("pointerleave", handlePointerLeave);

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
            <div class="mode-buttons">
                <button :class="{ active: viewMode === 'single' }" @click="setMode('single')">Beam</button>
                <button :class="{ active: viewMode === 'connected' }" @click="setMode('connected')">Connected</button>
                <button :class="{ active: viewMode === 'module' }" @click="setMode('module')">Module</button>
                <button :class="{ active: viewMode === 'pavilion' }" @click="setMode('pavilion')">Pavilion</button>
            </div>
            <div class="option-buttons">
                <label class="rotate-toggle">
                    <input v-model="isAutoRotating" type="checkbox" @change="setAutoRotate" />
                    Auto rotate
                </label>
                <label class="rotate-toggle">
                    <input v-model="preserveCameraOnViewChange" type="checkbox" />
                    Keep camera
                </label>
                <label class="rotate-toggle">
                    <input v-model="autoOrientBeamFrame" type="checkbox" @change="setMode(viewMode, { preserveCamera: false })" />
                    Flat beam view
                </label>
                <label v-if="viewMode !== 'single'" class="rotate-toggle">
                    <input v-model="colorCurrentModule" type="checkbox" @change="setMode(viewMode)" />
                    Color module
                </label>
                <label v-if="viewMode === 'pavilion'" class="rotate-toggle">
                    <input v-model="colorAllModules" type="checkbox" @change="setMode('pavilion')" />
                    Color all
                </label>
                <label v-if="viewMode === 'pavilion'" class="rotate-toggle">
                    <input v-model="showKeyBeams" type="checkbox" @change="setMode('pavilion')" />
                    Key beams
                </label>
            </div>
        </div>

        <div class="navigation-buttons">
            <div class="nav-group">
                <button class="nav-arrow nav-arrow-prev" title="Prev module" aria-label="Prev module" @click="navigateModule(-1)">
                    <span></span>
                </button>
                <span>Module {{ currentModule }} <template v-if="moduleCounter">({{ moduleCounter }})</template></span>
                <button class="nav-arrow nav-arrow-next" title="Next module" aria-label="Next module" @click="navigateModule(1)">
                    <span></span>
                </button>
            </div>
            <div class="nav-group">
                <button class="nav-arrow nav-arrow-prev" title="Prev beam" aria-label="Prev beam" @click="navigateBeam(-1)">
                    <span></span>
                </button>
                <span>{{ currentBeamId }} <template v-if="beamCounter">({{ beamCounter }})</template></span>
                <button class="nav-arrow nav-arrow-next" title="Next beam" aria-label="Next beam" @click="navigateBeam(1)">
                    <span></span>
                </button>
            </div>
        </div>

        <div class="weight-readout">
            Shown weight {{ totalShownWeight }} kg
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

        <div v-if="hoverInfo" class="hover-tooltip" :style="hoverStyle">
            <strong>{{ hoverInfo.title }}</strong>
            <span v-for="line in hoverInfo.lines" :key="line">{{ line }}</span>
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
    gap: 8px;
    font-family: "Helvetica Neue", sans-serif;
}

.view-buttons {
    top: 12px;
    left: 12px;
    align-items: flex-start;
}

.navigation-buttons {
    top: 12px;
    right: 12px;
    flex-direction: column;
    align-items: flex-end;
    max-width: min(520px, calc(100% - 220px));
    color: #111;
    font-size: 12px;
}

.mode-buttons,
.option-buttons,
.nav-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.nav-group {
    flex-direction: row;
    align-items: center;
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
}

.rotate-toggle {
    padding: 0;
    font-size: 11px;
    font-family: "Helvetica Neue", sans-serif;
    font-weight: 500;
    background: transparent;
    border: none;
    border-radius: 0;
}

.view-buttons button,
.navigation-buttons button {
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

.navigation-buttons > .nav-group > span {
    padding: 4px 8px;
    background: rgba(255, 255, 255, 0.75);
    text-align: center;
    min-width: 112px;
}

.navigation-buttons .nav-arrow {
    width: 25px;
    height: 25px;
    padding: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
}

.nav-arrow span {
    width: 0;
    height: 0;
    min-width: 0;
    padding: 0;
    background: transparent;
}

.nav-arrow-prev span {
    border-top: 5px solid transparent;
    border-bottom: 5px solid transparent;
    border-right: 8px solid #111;
}

.nav-arrow-next span {
    border-top: 5px solid transparent;
    border-bottom: 5px solid transparent;
    border-left: 8px solid #111;
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

.weight-readout {
    position: absolute;
    top: 12px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 10;
    padding: 5px 10px;
    background: rgba(255, 255, 255, 0.82);
    border: 1px solid #d0d0d0;
    color: #111;
    font-family: "Helvetica Neue", sans-serif;
    font-size: 12px;
    font-weight: 500;
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

.hover-tooltip {
    position: fixed;
    z-index: 30;
    pointer-events: none;
    display: flex;
    flex-direction: column;
    gap: 2px;
    max-width: 220px;
    padding: 6px 8px;
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid #cfcfcf;
    color: #111;
    font-family: "Helvetica Neue", sans-serif;
    font-size: 11px;
    line-height: 1.25;
    text-align: left;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
}

.hover-tooltip strong {
    font-size: 12px;
    line-height: 1.2;
}

@media (max-width: 760px) {
    .view-buttons {
        top: 8px;
        left: 8px;
        gap: 6px;
        max-width: 140px;
    }

    .navigation-buttons {
        top: 8px;
        right: 8px;
        left: auto;
        max-width: calc(100% - 158px);
        align-items: flex-end;
        gap: 4px;
        font-size: 10.5px;
    }

    .nav-group {
        gap: 3px;
        justify-content: flex-end;
    }

    .mode-buttons,
    .option-buttons {
        gap: 4px;
    }

    .view-buttons button {
        padding: 4.5px 8px;
        font-size: 10.5px;
        line-height: 1.1;
    }

    .rotate-toggle {
        gap: 4px;
        font-size: 9.5px;
        line-height: 1.1;
    }

    .rotate-toggle input {
        width: 12px;
        height: 12px;
    }

    .navigation-buttons > .nav-group > span {
        min-width: 82px;
        max-width: 116px;
        padding: 3px 4px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .navigation-buttons .nav-arrow {
        width: 20px;
        height: 20px;
    }

    .nav-arrow-prev span {
        border-top-width: 4px;
        border-bottom-width: 4px;
        border-right-width: 6px;
    }

    .nav-arrow-next span {
        border-top-width: 4px;
        border-bottom-width: 4px;
        border-left-width: 6px;
    }

    .weight-readout {
        top: auto;
        bottom: 74px;
        left: 8px;
        transform: none;
        padding: 3.5px 6px;
        font-size: 10px;
        border: none;
        background: rgba(255, 255, 255, 0.72);
    }

    .axis-legend {
        bottom: 8px;
        left: 8px;
        padding: 4px 6px;
        gap: 2px;
        font-size: 9px;
        border: none;
        background: rgba(255, 255, 255, 0.72);
    }

    .axis-dot {
        width: 8px;
        height: 8px;
    }

    .gizmo-canvas {
        width: 61px;
        height: 61px;
        right: 8px;
        bottom: 8px;
    }
}

@keyframes spin {
    to { transform: rotate(360deg); }
}
</style>
