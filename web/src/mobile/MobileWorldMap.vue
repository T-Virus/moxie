<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import WorldMap from '../components/WorldMap.vue'
import { api } from '../api'
import { state, store } from '../store'
import { toast } from '../ui'

const map = ref<any>(null)
const loading = ref(false)
const updated = ref('')

async function load() {
  const book = store.curBook()
  if (!book) { map.value = null; return }
  loading.value = true
  try {
    const r = await api.getBookMap(book)
    map.value = r.ok ? r.map : null
    updated.value = r.generated_at || ''
  } catch (e: any) {
    toast(e.message, 'err')
  } finally {
    loading.value = false
  }
}

watch(() => store.curBook(), load, { immediate: true })
onMounted(() => {
  state.books.length || store.loadBooks().catch(() => {})
  window.addEventListener('mowrite:data-changed', load)
})
onUnmounted(() => window.removeEventListener('mowrite:data-changed', load))
</script>

<template>
  <div class="m-page m-page-fixed">
    <div class="m-head">
      <div>
        <h1>世界地图</h1>
        <p>区域分布 · 势力与角色落点 · 章节事件，点区块查看详情</p>
      </div>
      <div class="m-head-act">
        <button class="m-btn sm" :disabled="loading" @click="load">
          <Icon name="refresh" :size="14" /> {{ loading ? '载入中' : '刷新' }}
        </button>
      </div>
    </div>

    <div class="m-page-scroll">
      <div v-if="loading && !map" class="m-card" style="padding:34px 16px;text-align:center">
        <p class="m-hint">正在读取地图数据…</p>
      </div>
      <template v-else>
        <WorldMap :map-data="map" mobile
                  hint="当前作品还没有地图数据：在客户端的「设定图谱 → 世界地图」重新生成一次，或导入包含图谱数据的数据包后回到这里查看。" />
        <p v-if="map && (map.regions || []).length" class="m-hint" style="padding:12px 6px 0">
          {{ updated ? '图谱更新于 ' + updated + '。' : '' }}
          角色的出场章与事件来自设定图谱；在客户端改名、删卡或调整章节后，地图会随数据一起同步，重新进入本页即可看到最新结果。
        </p>
      </template>
    </div>
  </div>
</template>
