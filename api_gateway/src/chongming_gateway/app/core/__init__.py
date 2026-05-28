"""
Gateway Core 模块
=================

包含核心组件：
- NATS 客户端管理 (nats_client.py)
- 动态路由管理 (dynamic_route.py)
- 日志配置 (logger.py)
"""

from chongming_logging import setup_gateway_logging

# 模块加载时自动配置 gateway 日志
setup_gateway_logging()
