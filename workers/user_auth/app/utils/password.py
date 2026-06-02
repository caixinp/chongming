"""
密码工具模块
=============

提供密码哈希和验证功能，使用 argon2 算法。
"""
import logging
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

logger = logging.getLogger("chongming.worker.user_auth")

# 全局 PasswordHasher 实例
_ph = PasswordHasher(
    time_cost=3,           # 迭代次数
    memory_cost=65536,     # 内存消耗（KB）
    parallelism=4,         # 并行度
    hash_len=32,           # 输出哈希长度
    salt_len=16,           # 盐长度
)


def hash_password(password: str) -> str:
    """对明文密码进行 argon2 哈希

    Parameters
    ----------
    password : str
        明文密码

    Returns
    -------
    str
        哈希后的密码字符串（包含盐和算法信息，可直接存储）
    """
    if not password or len(password) < 6:
        raise ValueError("密码长度不能少于 6 位")
    if len(password) > 128:
        raise ValueError("密码长度不能超过 128 位")
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """验证明文密码是否与哈希匹配

    Parameters
    ----------
    password : str
        待验证的明文密码
    password_hash : str
        存储的哈希密码字符串

    Returns
    -------
    bool
        密码匹配返回 True，否则返回 False
    """
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except (VerificationError, InvalidHashError) as e:
        logger.warning("密码验证异常: %s", e)
        return False


def needs_rehash(password_hash: str) -> bool:
    """检查哈希密码是否需要使用当前参数重新哈希

    当 argon2 的参数（time_cost, memory_cost 等）发生变化时，
    旧哈希需要重新计算以保持安全等级。

    Parameters
    ----------
    password_hash : str
        存储的哈希密码字符串

    Returns
    -------
    bool
        需要重新哈希返回 True
    """
    try:
        return _ph.check_needs_rehash(password_hash)
    except Exception as e:
        logger.warning("检查 rehash 状态异常: %s", e)
        return False
