/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { RefreshTokenResponse } from '../models/RefreshTokenResponse';
import type { TokenResponse } from '../models/TokenResponse';
import type { UserCreate } from '../models/UserCreate';
import type { UserLogin } from '../models/UserLogin';
import type { UserRead } from '../models/UserRead';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AuthenticationService {
    /**
     * Register
     * @param requestBody
     * @returns UserRead Successful Response
     * @throws ApiError
     */
    public static registerApiV1AuthRegisterPost(
        requestBody: UserCreate,
    ): CancelablePromise<UserRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/register',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Login
     * @param requestBody
     * @returns TokenResponse Successful Response
     * @throws ApiError
     */
    public static loginApiV1AuthLoginPost(
        requestBody: UserLogin,
    ): CancelablePromise<TokenResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/login',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 刷新访问令牌
     * @returns RefreshTokenResponse Successful Response
     * @throws ApiError
     */
    public static refreshTokenApiV1AuthRefreshPost(): CancelablePromise<RefreshTokenResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/refresh',
        });
    }
    /**
     * Logout
     * @returns any Successful Response
     * @throws ApiError
     */
    public static logoutApiV1AuthLogoutPost(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/logout',
        });
    }
    /**
     * 登出所有设备
     * @returns any Successful Response
     * @throws ApiError
     */
    public static logoutAllApiV1AuthLogoutAllPost(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/logout-all',
        });
    }
    /**
     * 获取用户会话
     * 获取用户的所有活跃会话
     * @returns any Successful Response
     * @throws ApiError
     */
    public static getSessionsApiV1AuthSessionsGet(): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/auth/sessions',
        });
    }
    /**
     * 获取当前用户信息
     * 获取当前登录用户的信息
     * @returns UserRead Successful Response
     * @throws ApiError
     */
    public static getCurrentUserInfoApiV1AuthMeGet(): CancelablePromise<UserRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/auth/me',
        });
    }
}
