<script setup>
import { onMounted, ref } from 'vue'
import * as THREE from 'three'

const containerRef = ref(null)
let scene, camera, renderer
let cube // Example 3D object

onMounted(() => {
  // Scene setup
  scene = new THREE.Scene()
  scene.background = new THREE.Color(0x1a1a2e)

  // Camera setup
  const width = containerRef.value.clientWidth
  const height = containerRef.value.clientHeight
  camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000)
  camera.position.z = 3

  // Renderer setup
  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(width, height)
  renderer.setPixelRatio(window.devicePixelRatio)
  containerRef.value.appendChild(renderer.domElement)

  // Create a simple cube as example
  const geometry = new THREE.BoxGeometry()
  const material = new THREE.MeshPhongMaterial({ color: 0xc084fc })
  cube = new THREE.Mesh(geometry, material)
  scene.add(cube)

  // Add lighting
  const light = new THREE.DirectionalLight(0xffffff, 1)
  light.position.set(5, 5, 5)
  scene.add(light)

  const ambientLight = new THREE.AmbientLight(0xffffff, 0.5)
  scene.add(ambientLight)

  // Animation loop
  const animate = () => {
    requestAnimationFrame(animate)
    cube.rotation.x += 0.01
    cube.rotation.y += 0.01
    renderer.render(scene, camera)
  }
  animate()

  // Handle window resize
  const handleResize = () => {
    const newWidth = containerRef.value.clientWidth
    const newHeight = containerRef.value.clientHeight
    camera.aspect = newWidth / newHeight
    camera.updateProjectionMatrix()
    renderer.setSize(newWidth, newHeight)
  }

  window.addEventListener('resize', handleResize)

  return () => {
    window.removeEventListener('resize', handleResize)
    renderer.dispose()
  }
})
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
}
</style>
