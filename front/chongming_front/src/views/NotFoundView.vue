<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
    <div class="notfound-container">
        <el-result icon="error" title="404" sub-title="抱歉，您访问的页面不存在">
            <template #extra>
                <el-button type="primary" @click="router.push('/dashboard')">返回首页</el-button>
            </template>
        </el-result>
    </div>
</template>

<style scoped>
.notfound-container {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
}
</style>