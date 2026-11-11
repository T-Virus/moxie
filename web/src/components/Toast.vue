<script setup lang="ts">
import { ui } from '../ui'
</script>

<template>
  <Teleport to="body">
    <div id="toast-root">
      <transition-group name="fade">
        <div v-for="t in ui.toasts" :key="t.id" class="toast" :class="t.type">{{ t.msg }}</div>
      </transition-group>
    </div>
  </Teleport>
</template>
