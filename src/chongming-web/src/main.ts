import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { OpenAPI } from "./api/generated"

/**
 * 打包时注释该项
 */
OpenAPI.BASE = "http://localhost:8000"
const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
