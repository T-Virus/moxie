<script setup lang="ts">
import { computed } from 'vue'
import { api } from '../api'

/* 统一的书本封面：有图显示图，没有图用「默认书本封面」排版（书名竖排 + 作者 + 墨印） */
const props = withDefaults(defineProps<{
  name: string
  title?: string
  author?: string
  hasCover?: boolean
  size?: 'xs' | 'sm' | 'md' | 'lg'
  tick?: number
}>(), { size: 'md', tick: 0 })

const src = computed(() => api.coverUrl(props.name, props.tick || 0))
const shownTitle = computed(() => (props.title || props.name || '未命名').slice(0, 18))
</script>

<template>
  <div class="m-book-art" :class="'sz-' + size">
    <img v-if="hasCover" :src="src" alt="封面" />
    <div v-else class="m-book-art-ph">
      <span class="m-book-art-title">{{ shownTitle }}</span>
      <span class="m-book-art-author">{{ author || '墨写' }} 著</span>
      <i class="m-book-art-seal">墨</i>
    </div>
  </div>
</template>

<style scoped>
.m-book-art {
  position: relative; flex: none; overflow: hidden; border-radius: 6px;
  background: linear-gradient(160deg, #223230, #0f1c1a); color: #fff;
  box-shadow: 0 6px 18px rgba(12, 30, 27, .22);
}
.m-book-art > img { width: 100%; height: 100%; object-fit: cover; display: block; }
.m-book-art-ph { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; padding: 8% 6%; }
.m-book-art-ph::before {
  content: ''; position: absolute; inset: 0;
  background:
    radial-gradient(circle at 78% 18%, rgba(35, 156, 139, .34), transparent 46%),
    radial-gradient(circle at 18% 88%, rgba(184, 137, 75, .22), transparent 52%);
}
.m-book-art-title {
  position: relative; writing-mode: vertical-rl; text-orientation: upright;
  font-family: "Songti SC", "Noto Serif SC", serif; font-weight: 700;
  letter-spacing: 3px; line-height: 1.25; text-align: start;
  max-height: 72%; overflow: hidden; margin-right: auto;
  text-shadow: 0 2px 8px rgba(0, 0, 0, .3);
}
.m-book-art-author {
  position: relative; margin-top: auto; align-self: flex-start;
  font-size: 8px; letter-spacing: 1px; opacity: .62; white-space: nowrap;
}
.m-book-art-seal {
  position: absolute; right: 8%; bottom: 7%; width: 22%; aspect-ratio: 1;
  border: 1px solid rgba(231, 196, 141, .7); border-radius: 3px;
  display: grid; place-items: center; color: #e7c48d; font-style: normal;
  font-family: "Songti SC", serif; font-size: 10px; opacity: .9;
}
/* 尺寸 */
.sz-xs { width: 24px; height: 32px; border-radius: 4px; }
.sz-xs .m-book-art-title { font-size: 7px; letter-spacing: 1px; }
.sz-xs .m-book-art-author, .sz-xs .m-book-art-seal { display: none; }
.sz-sm { width: 30px; height: 40px; border-radius: 5px; }
.sz-sm .m-book-art-title { font-size: 8px; letter-spacing: 1px; }
.sz-sm .m-book-art-author { display: none; }
.sz-sm .m-book-art-seal { width: 6px; height: 6px; font-size: 0; border-radius: 1px; }
.sz-md { width: 62px; height: 84px; border-radius: 7px; }
.sz-md .m-book-art-title { font-size: 11px; letter-spacing: 2px; }
.sz-md .m-book-art-author { font-size: 6.5px; }
.sz-lg { width: 108px; height: 146px; border-radius: 9px; }
.sz-lg .m-book-art-title { font-size: 17px; letter-spacing: 3px; }
.sz-lg .m-book-art-author { font-size: 8.5px; }
.sz-lg .m-book-art-seal { font-size: 13px; }
</style>
