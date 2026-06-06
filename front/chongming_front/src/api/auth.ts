import { handlerUserAuthUserLoginPost, handlerUserAuthUserroleListPost } from './generated/sdk.gen'
import type { UserLoginResponse, UserroleListResponse } from './generated/types.gen'

export async function login(username: string, password: string): Promise<UserLoginResponse> {
    const response = await handlerUserAuthUserLoginPost({
        query: { username, password },
    })
    return response.data as UserLoginResponse
}

export async function getUserPermissions(userId: string): Promise<UserroleListResponse> {
    const response = await handlerUserAuthUserroleListPost({
        query: { user_id: userId },
    })
    return response.data as UserroleListResponse
}