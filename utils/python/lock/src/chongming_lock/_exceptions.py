"""🔒 Chongming Lock — 自定义异常"""


class LockError(Exception):
    """锁操作基础异常"""
    pass


class LockNotAcquiredError(LockError):
    """无法获取锁（超时或已被占用）"""
    pass


class LockNotOwnedError(LockError):
    """尝试释放不属于自己的锁"""
    pass


class LockReleaseError(LockError):
    """锁释放失败"""
    pass


class LockStateError(LockError):
    """锁状态异常（如重入计数不匹配）"""
    pass
