import { defineStore } from "pinia"
import { ElMessage } from 'element-plus'
import { client } from "@/api/generated/client.gen"
import { loginApiV1AuthLoginPost, registerApiV1AuthRegisterPost } from "@/api/generated"


interface AuthState {
    accessToken: string | null
    refreshToken: string | null
}

export const useAuthStore = defineStore("auth", {
    state: (): AuthState => ({
        accessToken: localStorage.getItem("access_token"),
        refreshToken: localStorage.getItem("refresh_token"),
    }),
    actions: {
        setTokens(access: string, refresh: string) {
            this.accessToken = access
            this.refreshToken = refresh
            localStorage.setItem("access_token", access)
            localStorage.setItem("refresh_token", refresh)
            client.setConfig({
                auth: () => this.accessToken || ''
            })
        },
        clearTokens() {
            this.accessToken = null
            this.refreshToken = null
            localStorage.removeItem("access_token")
            localStorage.removeItem("refresh_token")
            client.setConfig({ auth: undefined })
        },
        async login(email: string, password: string) {
            try {
                const { data } = await loginApiV1AuthLoginPost({
                    body: { email, password },
                    throwOnError: true,
                })
                if (data) {
                    this.setTokens(data.access_token, data.refresh_token)
                    ElMessage.success("登录成功")
                    return true
                }
                return false
            } catch (error: any) {
                // console.error("登录失败", error)
                ElMessage.error(error.message || "登录失败")
                return false
            }
        },
        async register(email: string, password: string, username?: string) {
            try {
                await registerApiV1AuthRegisterPost({
                    body: { email, password, username },
                    throwOnError: true,
                })
                ElMessage.success("注册成功")
                return await this.login(email, password)
            } catch (error: any) {
                ElMessage.error(error.message || "注册失败")
                return false
            }
        },
        logout() {
            this.clearTokens()
            ElMessage.info("已退出登录")
        },
        initAuth() {
            if (this.accessToken) {
                client.setConfig({
                    auth: () => this.accessToken || ''
                })
            }
        }
    }
})