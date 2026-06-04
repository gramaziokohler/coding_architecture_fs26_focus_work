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
let scene, camera, renderer, model, controls;
let animationId;

const loadModel = (stlUrl) => {
    console.log("🔍 Loading STL from:", stlUrl);

    // Fetch the file first to handle CORS
    fetch(stlUrl, {
        mode: "cors",
        headers: {
            Accept: "*/*",
        },
    })
        .then((response) => {
            console.log("📥 Fetch response status:", response.status);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.arrayBuffer();
        })
        .then((arrayBuffer) => {
            console.log(
                "✅ STL file fetched, size:",
                arrayBuffer.byteLength,
                "bytes",
            );

            const geometry = STLLoader.prototype.parse(arrayBuffer);

            console.log(
                "✅ STL parsed successfully, geometry vertices:",
                geometry.attributes.position.count,
            );

            // Remove old model if exists
            if (model) {
                scene.remove(model);
            }

            // Create beige/wood material
            const material = new THREE.MeshPhongMaterial({
                color: 0xf0dec5,
                shininess: 30,
                side: THREE.DoubleSide,
            });

            // Create mesh from geometry
            model = new THREE.Mesh(geometry, material);
            model.castShadow = true;
            model.receiveShadow = true;

            scene.add(model);
            console.log("✅ Model added to scene");

            // Center and scale model
            geometry.computeBoundingBox();
            const center = new THREE.Vector3();
            geometry.boundingBox.getCenter(center);
            geometry.translate(-center.x, -center.y, -center.z);

            const size = new THREE.Vector3();
            geometry.boundingBox.getSize(size);
            const maxDim = Math.max(size.x, size.y, size.z);
            const scale = 2 / maxDim;

            model.scale.multiplyScalar(scale);
            console.log("✅ Model centered and scaled");

            // Update controls target to center of model
            controls.target.set(0, 0, 0);
            controls.update();
            console.log("✅ Controls updated");
        })
        .catch((error) => {
            console.error("❌ Error loading STL model:", error);
            console.error("Error message:", error.message);
        });
};

onMounted(async () => {
    console.log("🚀 ModelViewer mounting...");

    // Scene setup
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0xffffff);

    // Camera setup (Z-up coordinate system)
    const width = containerRef.value.clientWidth;
    const height = containerRef.value.clientHeight;
    camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);
    camera.position.set(3, 3, 2);
    camera.up.set(0, 0, 1);

    // Renderer setup
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    containerRef.value.appendChild(renderer.domElement);

    // OrbitControls setup
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 4;
    controls.enableZoom = true;
    controls.enablePan = true;
    controls.target.set(0, 0, 0);

    // Add lighting
    const directionalLight = new THREE.DirectionalLight(0xffffff, 1.2);
    directionalLight.position.set(5, 8, 5);
    directionalLight.castShadow = true;
    directionalLight.shadow.mapSize.width = 2048;
    directionalLight.shadow.mapSize.height = 2048;
    scene.add(directionalLight);

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
    scene.add(ambientLight);

    const fillLight = new THREE.DirectionalLight(0xffffff, 0.4);
    fillLight.position.set(-5, 3, -5);
    scene.add(fillLight);

    // Fetch beam JSON and load model
    try {
        if (!props.beamUrl) {
            throw new Error("No beam URL provided");
        }

        console.log("📍 Beam URL:", props.beamUrl);

        // Construct JSON URL
        const beamName = props.beamUrl.split("/").pop();
        const jsonUrl = props.beamUrl + "/" + beamName + ".json";

        console.log("🔗 Fetching JSON from:", jsonUrl);

        const response = await fetch(jsonUrl);
        if (!response.ok) {
            throw new Error(
                `Failed to fetch beam data: ${response.status} ${response.statusText}`,
            );
        }
        const beamData = await response.json();

        console.log("📦 Beam data loaded:", beamData);

        if (!beamData["3d_model"]) {
            throw new Error("No 3D model URL in beam data");
        }

        console.log("🎯 3D Model URL from JSON:", beamData["3d_model"]);
        loadModel(beamData["3d_model"]);
    } catch (error) {
        console.error("❌ Error loading beam:", error);
    }

    // Animation loop
    const animate = () => {
        animationId = requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
    };
    animate();

    // Handle window resize
    const handleResize = () => {
        const newWidth = containerRef.value.clientWidth;
        const newHeight = containerRef.value.clientHeight;
        camera.aspect = newWidth / newHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(newWidth, newHeight);
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
    <div ref="containerRef" class="model-viewer"></div>
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
</style>
