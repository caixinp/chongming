"""
Handler 注册模块
=================

将所有 handler 模块导入即可完成注册：

    from app.handlers import calc, user, order, system

各模块通过 from app.bootstrap import app 获取全局 app 实例，
使用 @app.handler() 装饰器注册。
"""

from app.handlers import calc, order, user, system

__all__ = ["calc", "order", "user", "system"]
