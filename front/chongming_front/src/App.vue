<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import MainLayout from '@/components/MainLayout.vue'

const route = useRoute()

/**
 * 判断当前路径是否需要 MainLayout（即已登录后的布局）
 * 登录页、403、404 不需要布局
 */
const isAuthPage = computed(() => {
    const noLayoutRoutes = ['login', 'forbidden', 'notFound']
    return noLayoutRoutes.includes(route.name as string)
})
</script>

<template>
    <MainLayout v-if="!isAuthPage" />
    <router-view v-else />
</template>

<style>
/* 全局样式重置 */
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

html,
body,
#app {
    height: 100%;
    font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB',
        'Microsoft YaHei', '微软雅黑', Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}
</style>