/**
 * 导航栏配置
 *
 * 每个导航项对应一个权限名称（permission name），
 * 只有拥有该权限的用户才能看到对应导航项。
 * 这是根据 RBAC 系统动态渲染导航栏的依据。
 */

export interface NavItem {
    /** 导航标题 */
    title: string
    /** 路由路径 */
    path: string
    /** 路由名称（需与 router 中定义一致） */
    routeName: string
    /** 所需权限名（subject 格式，如 "user.login"）。null 表示所有登录用户可见 */
    permission: string | null
    /** Element Plus 图标名 */
    icon: string
    /** 子导航项（可选） */
    children?: NavItem[]
}

export const navigationConfig: NavItem[] = [
    {
        title: '首页',
        path: '/dashboard',
        routeName: 'dashboard',
        permission: null, // 所有登录用户可见
        icon: 'HomeFilled',
    },
    {
        title: '用户管理',
        path: '/users',
        routeName: 'users',
        permission: 'user.login', // 拥有用户管理权限才可见
        icon: 'User',
        children: [
            {
                title: '角色管理',
                path: '/roles',
                routeName: 'roles',
                permission: 'role.list',
                icon: 'Avatar',
            },
            {
                title: '权限管理',
                path: '/permissions',
                routeName: 'permissions',
                permission: 'permission.list',
                icon: 'Key',
            },
        ],
    },
    {
        title: '系统管理',
        path: '/system',
        routeName: 'system',
        permission: 'role.create', // 示例：高级权限
        icon: 'Setting',
    },
]