<script setup>
defineProps({
  title: {
    type: String,
    default: '3D Model Viewer'
  },
  description: {
    type: String,
    default: 'Explore 3D models with our interactive viewer'
  }
})
</script>

<template>
  <div class="info-panel">
    <h1>{{ title }}</h1>
    <p>{{ description }}</p>
  </div>
</template>

<style scoped>
.info-panel {
  padding: 32px;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  text-align: center;

  @media (max-width: 1024px) {
    padding: 24px 20px;
  }
}

h1 {
  margin: 0 0 16px 0;
  font-size: 48px;
  color: var(--text-h);

  @media (max-width: 1024px) {
    font-size: 32px;
  }
}

p {
  margin: 0;
  font-size: 18px;
  color: var(--text);
  max-width: 600px;
  margin: 0 auto;
}
</style>
