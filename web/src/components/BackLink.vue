<script setup lang="ts">
import { useRouter } from 'vue-router'
import Icon from './Icon.vue'

const router = useRouter()
</script>

<template>
  <button class="btn ghost" @click="router.push('/overview')">
    <Icon name="left" :size="14" /> 返回详情
  </button>
</template>
