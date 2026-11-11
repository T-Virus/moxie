<script setup lang="ts">
import { ref } from 'vue'
import Icon from './Icon.vue'
const open = ref(false)
/* 首次展开后才挂载内容：display:none 只是不布局，DOM 仍会创建，
   上千个面板的表单控件常驻会把页面拖垮（章节概括 1396 章卡死） */
const opened = ref(false)
function toggle() {
  open.value = !open.value
  if (open.value) opened.value = true
}
</script>

<template>
  <div class="collapse" :class="{ open }">
    <div class="collapse-head" @click="toggle">
      <slot name="head" />
    </div>
    <div class="collapse-body"><div v-if="opened"><slot /></div></div>
  </div>
</template>

<style scoped>
</style>
