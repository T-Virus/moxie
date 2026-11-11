// 内联 SVG 图标集合（线性风格，统一 24x24）
const s = (inner: string) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`

export const ICONS: Record<string, string> = {
  dashboard: s('<rect x="3" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5"/>'),
  upload: s('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M12 17v-6"/><path d="m9.5 13.5 2.5-2.5 2.5 2.5"/>'),
  list: s('<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3.5 6h.01"/><path d="M3.5 12h.01"/><path d="M3.5 18h.01"/>'),
  pen: s('<path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/>'),
  movie: s('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 4v16"/><path d="M16 4v16"/><path d="M3 9h5"/><path d="M16 9h5"/><path d="M3 15h5"/><path d="M16 15h5"/>'),
  shield: s('<path d="M12 2 4 5v6c0 5.25 3.4 9.74 8 11 4.6-1.26 8-5.75 8-11V5Z"/><path d="m9 12 2 2 4-4"/>'),
  folder: s('<path d="M4 5h5l2 2.5h9a1 1 0 0 1 1 1V19a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z"/>'),
  search: s('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/>'),
  /* 地图：折页地图 + 定位点，用于「世界地图 / 区域分布」 */
  map: s('<path d="M9 4 3 6.5v14L9 18l6 2.5 6-2.5v-14L15 6.5Z"/><path d="M9 4v14"/><path d="M15 6.5v14"/>'),
  /* 图谱：三个节点由连线相连，用于「生成图谱 / 设定图谱」 */
  graph: s('<circle cx="6" cy="6.5" r="2.5"/><circle cx="18" cy="7.5" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8.4 7.1 15.5 7.4"/><path d="m7.3 8.7 3.4 7.2"/><path d="m16.6 9.6-3.3 6.3"/>'),
  plus: s('<path d="M12 5v14M5 12h14"/>'),
  down: s('<path d="m6 9 6 6 6-6"/>'),
  close: s('<path d="M6 6l12 12M18 6 6 18"/>'),
  book: s('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>'),
  check: s('<path d="m4.5 12.5 5 5 10-11"/>'),
  arrowR: s('<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>'),
  arrowDown: s('<path d="m9 6 6 6-6 6"/>'),
  play: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M7 4.8a1 1 0 0 1 1.5-.86l11 6.2a1 1 0 0 1 0 1.73l-11 6.2A1 1 0 0 1 7 17.3Z"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
  trash: s('<path d="M4 7h16"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path d="M6 7l1 13a1 1 0 0 0 1 .9h8a1 1 0 0 0 1-.9L18 7"/><path d="M10 11v6M14 11v6"/>'),
  eye: s('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>'),
  file: s('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'),
  cloud: s('<path d="M12 13v8"/><path d="m8 17 4 4 4-4"/><path d="M20.4 15.5A5.5 5.5 0 0 0 18 5.1 7.5 7.5 0 0 0 3.7 8.6 4.5 4.5 0 0 0 5 17"/>'),
  settings: s('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.01a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.01a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1Z"/>'),
  download: s('<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>'),
  right: s('<path d="m9 6 6 6-6 6"/>'),
  left: s('<path d="m15 18-6-6 6-6"/>'),
  edit: s('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>'),
  copy: s('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>'),
  user: s('<circle cx="12" cy="7.5" r="3.5"/><path d="M5.5 20.5c.7-3.6 3.3-5.7 6.5-5.7s5.8 2.1 6.5 5.7"/>'),
  flag: s('<path d="M5 21V4"/><path d="M5 5h12.5l-2.6 3.5 2.6 3.5H5"/>'),
  expand: s('<path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="m21 3-7 7"/><path d="m3 21 7-7"/>'),
  /* 任务中心：队列列表（左侧方块代表任务，右侧横线代表日志行） */
  tasks: s('<rect x="3" y="4" width="3.6" height="3.6" rx="1"/><rect x="3" y="10.2" width="3.6" height="3.6" rx="1"/><rect x="3" y="16.4" width="3.6" height="3.6" rx="1"/><path d="M10 5.8h10"/><path d="M10 12h10"/><path d="M10 18.2h6"/>'),
  refresh: s('<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M20.5 4.5v4.8h-4.8"/>'),
  shrink: s('<path d="M4 14h6v6"/><path d="M20 10h-6V4"/><path d="m14 10 7-7"/><path d="m3 21 7-7"/>'),
  /* 汉堡菜单：移动端展开侧边栏抽屉 */
  menu: s('<path d="M4 6.5h16"/><path d="M4 12h16"/><path d="M4 17.5h16"/>'),
}
