# Chongming Front — 微服务管理面板

[![Vue 3](https://img.shields.io/badge/Vue-3.5-4FC08D.svg)](https://vuejs.org/)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF.svg)](https://vite.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6.svg)](https://www.typescriptlang.org/)

Chongming 微服务管理前端面板，基于 **Vue 3 + Vite + TypeScript** 构建，提供可视化的服务管理界面，方便监控 Worker 状态、查看路由注册和调试 API。

---

## 技术栈

| 技术 | 用途 |
|------|------|
| **Vue 3** (Composition API + `<script setup>`) | 前端框架 |
| **Vue Router** | 客户端路由 |
| **Pinia** | 状态管理 |
| **Vite 6** | 构建工具 |
| **TypeScript 5.7** | 类型安全 |

---

## 快速开始

```bash
cd front/chongming_front

# 安装依赖
npm install

# 启动开发服务器（热重载）
npm run dev

# 生产构建
npm run build

# 预览生产构建
npm run preview
```

---

## 项目结构

```
src/
├── main.ts              # 应用入口
├── App.vue              # 根组件
├── router/
│   └── index.ts         # 路由配置（HomeView / AboutView）
├── stores/
│   └── counter.ts       # Pinia 状态管理示例
├── views/
│   ├── HomeView.vue     # 首页
│   └── AboutView.vue    # 关于页面
├── components/
│   ├── HelloWorld.vue   # 示例组件
│   ├── TheWelcome.vue
│   └── WelcomeItem.vue
├── assets/
│   ├── main.css         # 全局样式
│   ├── base.css         # 基础样式
│   └── logo.svg
└── icons/               # SVG 图标组件
    ├── IconCommunity.vue
    ├── IconDocumentation.vue
    ├── IconEcosystem.vue
    ├── IconSupport.vue
    └── IconTooling.vue
```

---

## 开发配置

### 推荐的 IDE 设置

- [VS Code](https://code.visualstudio.com/) + [Vue (Official)](https://marketplace.visualstudio.com/items?itemName=Vue.volar) 扩展
- 推荐**禁用 Vetur**，使用 Volar
- 配合 TypeScript Vue Plugin (Volar) 获得 `.vue` 文件类型推断

### 推荐的浏览器

- Chromium 内核浏览器（Chrome、Edge、Brave 等）
- [Vue.js Devtools](https://chromewebstore.google.com/detail/vuejs-devtools/nhdogjmejiglipccpnnnanhbledajbpd)
- 在 Chrome DevTools 中[启用 Custom Object Formatter](http://bit.ly/object-formatters)

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
- [Vue 3 文档](https://vuejs.org/)

---

## 与后端集成

管理面板需要与运行中的 API Gateway 配合使用。默认配置下：

- 开发服务器运行在 `http://localhost:5173`
- API Gateway 运行在 `http://localhost:8000`
- 通过 Vite 代理配置转发 API 请求

```typescript
// vite.config.ts 示例
export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
