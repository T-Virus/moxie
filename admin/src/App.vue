<script setup lang="ts">
import ToastStack from './components/ToastStack.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
</script>

<template>
  <router-view />
  <ToastStack />
  <ConfirmDialog />
</template>
