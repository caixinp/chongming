# Chongming Front — 微服务管理面板

[![Vue 3](https://img.shields.io/badge/Vue-3.5-4FC08D.svg)](https://vuejs.org/)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF.svg)](https://vite.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6.svg)](https://www.typescriptlang.org/)

Chongming 微服务管理前端面板，基于 Vue 3 + Vite + TypeScript 构建，提供可视化的服务管理界面。

---

## 技术栈

| 技术 | 用途 |
|------|------|
| **Vue 3** (Composition API) | 前端框架 |
| **Vue Router** | 客户端路由 |
| **Pinia** | 状态管理 |
| **Vite** | 构建工具 |
| **TypeScript** | 类型安全 |

---

## 快速开始

```bash
# 安装依赖
cd front/chongming_front
npm install

# 启动开发服务器（热重载）
npm run dev

# 生产构建
npm run build
```

---

## 开发配置

### 推荐的 IDE 设置

- [VS Code](https://code.visualstudio.com/) + [Vue (Official)](https://marketplace.visualstudio.com/items?itemName=Vue.volar)
- 推荐禁用 Vetur，使用 Volar

### 推荐的浏览器

- Chromium 内核浏览器（Chrome、Edge、Brave 等）：
  - [Vue.js devtools](https://chromewebstore.google.com/detail/vuejs-devtools/nhdogjmejiglipccpnnnanhbledajbpd)
  - [在 Chrome DevTools 中启用 Custom Object Formatter](http://bit.ly/object-formatters)

### TypeScript 支持

`.vue` 文件的类型推断需要 Volar 支持。构建时使用 `vue-tsc` 替代 `tsc` 进行类型检查。

---

## 项目结构

```
src/
├── main.ts              # 应用入口
├── App.vue              # 根组件
├── router/              # 路由配置
│   └── index.ts
├── stores/              # Pinia 状态管理
│   └── counter.ts
├── views/               # 页面组件
│   ├── HomeView.vue
│   └── AboutView.vue
├── components/          # 通用组件
│   ├── HelloWorld.vue
│   ├── TheWelcome.vue
│   └── WelcomeItem.vue
├── assets/              # 静态资源
│   ├── main.css
│   ├── base.css
│   └── logo.svg
└── icons/               # SVG 图标组件
    ├── IconCommunity.vue
    ├── IconDocumentation.vue
    ├── IconEcosystem.vue
    ├── IconSupport.vue
    └── IconTooling.vue
```

---

## 命令参考

| 命令 | 说明 |
|------|------|
| `npm run dev` | 启动开发服务器（热重载） |
| `npm run build` | 生产构建 |
| `npm run preview` | 预览生产构建 |
| `npm run type-check` | TypeScript 类型检查 |
| `npm run lint` | 代码风格检查 |

---

## 配置参考

- [Vite 配置](https://vite.dev/config/)
- [Vue Router](https://router.vuejs.org/)
- [Pinia](https://pinia.vuejs.org/)
