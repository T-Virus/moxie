<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()

/* 与桌面「内容模块」同序：势力 → 角色 → 道具 → 大纲 → 章节 → 正文（设定图谱仅桌面有） */
const tabs = [
  { path: '/factions', label: '势力表', icon: 'flag' },
  { path: '/characters', label: '角色卡', icon: 'user' },
  { path: '/items', label: '道具功法', icon: 'shield' },
  { path: '/outline', label: '作品大纲', icon: 'list' },
  { path: '/chapters', label: '章节概括', icon: 'file' },
  { path: '/manuscript', label: '正文', icon: 'book' },
]
const active = computed(() => {
  const hit = tabs.find(t => route.path === t.path || route.path.startsWith(t.path + '/'))
  return hit?.path || ''
})
</script>

<template>
  <nav class="m-tabbar">
    <button v-for="t in tabs" :key="t.path" class="m-tab" :class="{ on: active === t.path }"
            @click="router.push(t.path)">
      <span class="m-tab-ico"><Icon :name="t.icon" :size="20" /></span>
      <span class="m-tab-label">{{ t.label }}</span>
    </button>
  </nav>
</template>
