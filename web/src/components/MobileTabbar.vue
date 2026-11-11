<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from './Icon.vue'
import { ui } from '../ui'
import { useJobQueue } from '../composables/useJobQueue'

/* 手机端底栏：只放最常用的四个创作入口，「更多」打开完整侧栏抽屉，
   保证所有模块都能到达。桌面端由 CSS 隐藏。 */
const route = useRoute()
const router = useRouter()
const { running } = useJobQueue()

const tabs = [
  { path: '/overview', label: '概览', icon: 'dashboard' },
  { path: '/chapters', label: '章节', icon: 'list' },
  { path: '/expand', label: '正文', icon: 'pen' },
  { path: '/review', label: '审查', icon: 'shield' },
]
const moreActive = computed(() => !tabs.some(t => route.path === t.path))
</script>

<template>
  <nav class="mtb">
    <button v-for="t in tabs" :key="t.path" class="mtb-item"
            :class="{ on: route.path === t.path }" @click="router.push(t.path)">
      <span class="mtb-ico"><Icon :name="t.icon" :size="19" /></span>
      <span>{{ t.label }}</span>
    </button>
    <button class="mtb-item" :class="{ on: moreActive }" @click="ui.menuOpen = true">
      <span class="mtb-ico">
        <Icon name="menu" :size="19" />
        <i v-if="running" class="mtb-badge">{{ running > 9 ? '9+' : running }}</i>
      </span>
      <span>更多</span>
    </button>
  </nav>
</template>
