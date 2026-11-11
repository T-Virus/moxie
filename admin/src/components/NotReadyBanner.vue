<script setup lang="ts">
withDefaults(defineProps<{
  endpoint?: string
  title?: string
  message?: string
}>(), {
  title: '接口未就绪',
  message: '该管理接口尚未在服务端实现。页面已按既有 OpenAPI 约定完成封装，服务端就绪后无需改动前端即可启用。',
})
</script>

<template>
  <div class="notice warn">
    <div class="notice-body">
      <div class="notice-title">{{ title }}<code v-if="endpoint" style="margin-left: 8px">{{ endpoint }}</code></div>
      <div style="margin-top: 3px">{{ message }}</div>
      <slot />
    </div>
  </div>
</template>
