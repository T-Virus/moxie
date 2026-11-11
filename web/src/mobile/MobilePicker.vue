<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'

/**
 * 安卓端单选选择器：触发器 + 底部弹层。
 * 原生 select 在 WebView 里是系统级列表，选项一多（角色 / 势力 / 关系类型）就难找，
 * 这里统一换成可搜索的底部弹层，选中即关闭，视觉与 App 其它浮层一致。
 */
const props = withDefaults(defineProps<{
  modelValue: string
  options: (string | { label: string; value: string })[]
  title: string
  placeholder?: string
  /* 是否提供「未填 / 清除」一项 */
  allowEmpty?: boolean
  emptyLabel?: string
  disabled?: boolean
  /* 选项超过这个数量才显示搜索框 */
  searchFrom?: number
  /* 允许直接输入自定义值（种族这类可自由填写的字段） */
  allowCustom?: boolean
  /* 紧凑胶囊样式（用在封面状态这类小位置），弹层行为不变 */
  chip?: boolean
}>(), {
  placeholder: '请选择',
  allowEmpty: true,
  emptyLabel: '— 未填 —',
  disabled: false,
  searchFrom: 8,
  allowCustom: false,
  chip: false,
})

const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const open = ref(false)
const kw = ref('')
watch(open, v => { if (v) kw.value = '' })

type Opt = { label: string; value: string }
const opts = computed<Opt[]>(() => (props.options || []).map(o =>
  typeof o === 'string' ? { label: o, value: o } : o))
const list = computed(() => {
  const q = kw.value.trim().toLowerCase()
  return q ? opts.value.filter(o => o.label.toLowerCase().includes(q)) : opts.value
})
const showSearch = computed(() => props.allowCustom || (props.options || []).length > props.searchFrom)
const customText = computed(() => kw.value.trim())
const showCustom = computed(() => props.allowCustom && !!customText.value
  && !opts.value.some(o => o.value === customText.value))
const curLabel = computed(() => {
  const hit = opts.value.find(o => o.value === props.modelValue)
  return hit ? hit.label : (props.modelValue || '')
})

function pick(v: string) {
  emit('update:modelValue', v)
  open.value = false
}
</script>

<template>
  <button type="button" class="mp-trigger" :class="{ 'mp-chip': chip }" :disabled="disabled" @click="open = true">
    <span class="mp-trigger-txt" :class="{ ph: !curLabel }">{{ curLabel || placeholder }}</span>
    <Icon name="down" :size="13" class="mp-chev" />
  </button>

  <Modal :open="open" :title="title" @update:open="v => open = v">
    <div class="mp-sheet">
      <div v-if="showSearch" class="mp-search">
        <Icon name="search" :size="15" />
        <input v-model="kw" :placeholder="allowCustom ? '输入筛选，或直接输入自定义值' : '输入关键词筛选'" />
        <button v-if="kw" class="m-clear" type="button" @click="kw = ''">
          <Icon name="close" :size="13" />
        </button>
      </div>

      <button v-if="showCustom" type="button" class="mp-item mp-custom" @click="pick(customText)">
        <span>使用自定义：{{ customText }}</span>
        <Icon name="plus" :size="14" />
      </button>

      <button v-if="allowEmpty" type="button" class="mp-item" :class="{ on: !modelValue }"
              @click="pick('')">
        <span>{{ emptyLabel }}</span>
        <Icon v-if="!modelValue" name="check" :size="15" />
      </button>

      <button v-for="o in list" :key="o.value + '|' + o.label" type="button" class="mp-item"
              :class="{ on: modelValue === o.value }" @click="pick(o.value)">
        <span>{{ o.label }}</span>
        <Icon v-if="modelValue === o.value" name="check" :size="15" />
      </button>

      <p v-if="!list.length" class="m-hint" style="padding:16px 2px;text-align:center">
        没有匹配的选项
      </p>
    </div>
  </Modal>
</template>

<style scoped>
.mp-trigger {
  display: flex; align-items: center; gap: 8px; width: 100%;
  min-height: 44px; padding: 0 12px;
  border: 1px solid var(--m-line, #e4e6e1); border-radius: 12px;
  background: #fff; color: var(--m-text, #1f2622);
  font-size: 13px; text-align: left;
}
.mp-trigger:disabled { opacity: .5; }
.mp-trigger:active { background: #f7f9f5; }
/* 胶囊：嵌在别的小标签里时不抢背景，只做可点的文字 + 箭头 */
.mp-trigger.mp-chip {
  display: inline-flex; width: auto; min-height: 0; height: 22px;
  padding: 0; border: 0; border-radius: 0; background: transparent;
  font-size: 12px; color: inherit; gap: 3px;
}
.mp-trigger.mp-chip:active { background: transparent; }
.mp-trigger-txt {
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* 胶囊模式：文字和箭头贴在一起，不要被 flex 撑到整行两端 */
.mp-trigger.mp-chip .mp-trigger-txt { flex: none; }
.mp-trigger.mp-chip { color: var(--m-primary, #0f766e); font-weight: 600; }
.mp-trigger-txt.ph { color: var(--m-text3, #8b918a); }
.mp-chev { flex: none; color: var(--m-text3, #8b918a); }
.mp-sheet { display: flex; flex-direction: column; gap: 2px; }
.mp-search {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 8px; padding: 0 12px; height: 44px;
  border-radius: 12px; background: #f4f6f2; color: var(--m-text3, #8b918a);
}
.mp-search input {
  flex: 1; min-width: 0; border: 0; outline: none; background: none;
  color: var(--m-text, #1f2622); font-size: 16px;
}
.mp-item {
  display: flex; align-items: center; gap: 10px;
  width: 100%; min-height: 48px; padding: 0 12px;
  border: 0; border-radius: 12px; background: none;
  color: var(--m-text, #1f2622); font-size: 14px; text-align: left;
}
.mp-item:active { background: #f5f7f3; }
.mp-item.on { background: var(--m-primary-soft, #e7f4f0); color: var(--m-primary, #0f766e); font-weight: 650; }
.mp-item.mp-custom { color: var(--m-primary, #0f766e); font-weight: 600; }
.mp-item span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
