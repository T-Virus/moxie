<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

/* 动态高度虚拟列表：只渲染可视窗口附近的条目，支撑大数据量（数千条）流畅滚动。
   条目高度按实际渲染测量并缓存，未测量的用 estimate 估算，随滚动逐步校准。 */
const props = withDefaults(defineProps<{
  items: any[]
  estimate?: number
  keyOf?: (it: any, i: number) => string | number
  buffer?: number
}>(), { estimate: 96, buffer: 6 })

const GAP = 8
const wrap = ref<HTMLElement | null>(null)
const scrollTop = ref(0)
const vh = ref(600)
const heights = ref<number[]>([])

function h(i: number): number { return heights.value[i] ?? props.estimate }

/* 前缀偏移（含条目间距），O(n) 但 n 为可见数据量级，重算成本可忽略 */
const offsets = computed<number[]>(() => {
  const o = [0]
  for (let i = 0; i < props.items.length; i++) o.push(o[i] + h(i) + GAP)
  return o
})
const totalH = computed(() => offsets.value[props.items.length] || 0)
const start = computed(() => {
  const st = scrollTop.value
  let lo = 0, hi = props.items.length - 1, r = 0
  while (lo <= hi) { const m = (lo + hi) >> 1; if (offsets.value[m] <= st) { r = m; lo = m + 1 } else hi = m - 1 }
  return r
})
const end = computed(() => {
  const bottom = scrollTop.value + vh.value
  let e = start.value
  while (e < props.items.length && offsets.value[e] < bottom) e++
  return e
})
const win = computed(() => {
  const s = Math.max(0, start.value - props.buffer)
  const e = Math.min(props.items.length, end.value + props.buffer)
  const out: { item: any; index: number; top: number }[] = []
  for (let i = s; i < e; i++) out.push({ item: props.items[i], index: i, top: offsets.value[i] })
  return out
})

let measuring = false
function queueMeasure() {
  if (measuring) return
  measuring = true
  nextTick(() => {
    measuring = false
    const el = wrap.value
    if (!el) return
    el.querySelectorAll<HTMLElement>('[data-vi]').forEach(n => {
      const i = Number(n.getAttribute('data-vi'))
      const hgt = n.offsetHeight
      if (i >= 0 && hgt > 0) heights.value[i] = hgt
    })
  })
}

function onScroll() {
  scrollTop.value = wrap.value?.scrollTop || 0
  queueMeasure()
}
function onResize() { vh.value = wrap.value?.clientHeight || 600 }

let ro: ResizeObserver | null = null
onMounted(() => {
  onResize()
  queueMeasure()
  ro = new ResizeObserver(onResize)
  if (wrap.value) ro.observe(wrap.value)
})
onBeforeUnmount(() => ro?.disconnect())

watch(() => props.items.length, () => {
  heights.value = []
  scrollTop.value = 0
  if (wrap.value) wrap.value.scrollTop = 0
  queueMeasure()
})
</script>

<template>
  <div ref="wrap" class="vlist" @scroll.passive="onScroll">
    <div class="vlist-inner" :style="{ height: totalH + 'px' }">
      <div v-for="w in win" :key="keyOf ? keyOf(w.item, w.index) : w.index"
           class="vlist-item" :data-vi="w.index" :style="{ top: w.top + 'px' }">
        <slot :item="w.item" :index="w.index" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.vlist { overflow-y: auto; position: relative; }
.vlist-inner { position: relative; }
.vlist-item { position: absolute; left: 0; right: 0; }
</style>
