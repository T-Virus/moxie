import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { isMobileView } from './mobile/detect'

/* 同一个路由：安卓端渲染全新移动页面，桌面端保持原页面。
   在进入路由时判定一次，避免移动端误加载桌面端的大体积视图。 */
function view(desktop: () => Promise<any>, mobile: () => Promise<any>) {
  return () => (isMobileView() ? mobile() : desktop())
}

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/overview' },
  // 作品详情（选中作品的首页）
  { path: '/overview', name: 'overview',
    component: view(() => import('./views/Overview.vue'), () => import('./mobile/MobileCover.vue')),
    meta: { title: '作品详情' } },
  // 作品内容模块
  { path: '/outline', name: 'outline',
    component: view(() => import('./views/Outline.vue'), () => import('./mobile/MobileOutline.vue')),
    meta: { title: '作品大纲' } },
  { path: '/characters', name: 'characters',
    component: view(() => import('./views/Characters.vue'), () => import('./mobile/MobileCharacters.vue')),
    meta: { title: '角色卡' } },
  { path: '/factions', name: 'factions',
    component: view(() => import('./views/Factions.vue'), () => import('./mobile/MobileFactions.vue')),
    meta: { title: '势力表' } },
  { path: '/items', name: 'items',
    component: view(() => import('./views/Items.vue'), () => import('./mobile/MobileItems.vue')),
    meta: { title: '道具功法' } },
  { path: '/chapters', name: 'chapters',
    component: view(() => import('./views/Chapters.vue'), () => import('./mobile/MobileChapters.vue')),
    meta: { title: '章节概括' } },
  /* 安卓端「正文」：成稿列表 + 沉浸阅读 / 编辑（桌面端不放入口） */
  { path: '/manuscript', name: 'manuscript', component: () => import('./mobile/MobileManuscript.vue'), meta: { title: '正文' } },
  { path: '/storymap', name: 'storymap', component: () => import('./views/Storymap.vue'), meta: { title: '设定图谱' } },
  /* 安卓端世界地图：桌面端走「设定图谱 → 世界地图」页签，这里只给移动端入口 */
  { path: '/world-map', name: 'world-map', component: () => import('./mobile/MobileWorldMap.vue'),
    beforeEnter: () => (isMobileView() ? true : { path: '/storymap' }),
    meta: { title: '世界地图' } },
  // 创作工具
  { path: '/expand', name: 'expand', component: () => import('./views/Expand.vue'), meta: { title: '正文生成' } },
  { path: '/adapt', name: 'adapt', component: () => import('./views/Adapt.vue'), meta: { title: '改编创作' } },
  { path: '/review', name: 'review', component: () => import('./views/Review.vue'), meta: { title: '单章审查' } },
  // 全局（bookScoped: false —— 不属于某本书的页面，顶部不回显作品信息）
  { path: '/upload', name: 'upload',
    component: view(() => import('./views/Upload.vue'), () => import('./mobile/MobileUpload.vue')),
    meta: { title: '新建作品', bookScoped: false } },
  { path: '/outputs', name: 'outputs',
    component: view(() => import('./views/Outputs.vue'), () => import('./mobile/MobileOutputs.vue')),
    meta: { title: '产出文件', bookScoped: false } },
  { path: '/tasks', name: 'tasks',
    component: view(() => import('./views/Tasks.vue'), () => import('./mobile/MobileTasks.vue')),
    meta: { title: '任务中心', bookScoped: false } },
  // 用量与成本统计（多模型档案 / 工序维度）
  { path: '/stats', name: 'stats',
    component: view(() => import('./views/Stats.vue'), () => import('./mobile/MobileStats.vue')),
    meta: { title: '用量统计', bookScoped: false } },
  // 安卓端设置：独立二级页（桌面端仍用工作台设置弹窗）
  { path: '/settings', name: 'settings', component: () => import('./mobile/MobileSettings.vue'),
    beforeEnter: () => (isMobileView() ? true : { path: '/overview' }),
    meta: { title: '设置', bookScoped: false } },
  // 安卓端 AI 封面 / 作品审查二级页
  { path: '/cover-design', name: 'cover-design', component: () => import('./mobile/MobileCoverDesign.vue'),
    beforeEnter: () => (isMobileView() ? true : { path: '/overview' }),
    meta: { title: 'AI 封面' } },
  { path: '/book-review', name: 'book-review', component: () => import('./mobile/MobileBookReview.vue'),
    beforeEnter: () => (isMobileView() ? true : { path: '/overview' }),
    meta: { title: '作品审查' } },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
