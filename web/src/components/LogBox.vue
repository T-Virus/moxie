<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'

const props = defineProps<{ lines: string[] }>()
const box = ref<HTMLElement | null>(null)

watch(() => props.lines.length, async () => {
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
})

function cls(line: string): string {
  if (/\[x\]|错误|Error|Traceback|失败/i.test(line)) return 'ln-err'
  if (/\[完成\]|退出码 0/i.test(line)) return 'ln-ok'
  if (/\[!\]|警告|跳过/i.test(line)) return 'ln-warn'
  return ''
}
</script>

<template>
  <div class="logbox" ref="box">
    <div v-for="(l, i) in lines" :key="i" :class="cls(l)">{{ l }}</div>
  </div>
</template>
