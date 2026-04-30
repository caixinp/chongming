// import './assets/main.css'
import 'element-plus/dist/index.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'


/**
 * 打包时取消该注释
 */
import { client } from "./api/generated/client.gen"
client.setConfig({
    baseUrl: "/"
})

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

const authStore = useAuthStore()
authStore.initAuth()

app.mount('#app')
