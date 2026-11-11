<script setup lang="ts">
import Icon from './Icon.vue'

const props = defineProps<{ running: boolean; code?: number | null; label?: string }>()
const emit = defineEmits<{ (e: 'stop'): void }>()

function stateClass(): string {
  return props.running ? 'run'
    : props.code === 0 ? 'ok'
    : props.code == null ? 'idle' : 'err'
}
function text(): string {
  if (props.running) return '任务运行中' + (props.label ? ' · ' + props.label : '')
  if (props.code === 0) return '任务完成'
  if (props.code == null) return '空闲'
  return '任务失败（退出码 ' + props.code + '）'
}
</script>

<template>
  <div class="jobbar">
    <span class="state" :class="stateClass()">
      <span class="dot"></span><span class="txt">{{ text() }}</span>
    </span>
    <span class="spacer" style="flex:1"></span>
    <button v-if="running" class="btn danger-ghost sm" @click="emit('stop')">
      <Icon name="stop" :size="14" /> 停止任务
    </button>
  </div>
</template>
