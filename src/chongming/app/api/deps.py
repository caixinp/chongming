from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from ..service.auth import get_auth_service
from ..core.jwt_cache import TokenData


access_scheme = HTTPBearer(scheme_name="AccessToken")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(access_scheme),
) -> TokenData:
    """
    获取当前用户依赖项

    验证访问令牌并返回用户信息
    """
    auth_service = get_auth_service()

    token = credentials.credentials
    token_data = await auth_service.validate_access_token(token)

    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token_data
