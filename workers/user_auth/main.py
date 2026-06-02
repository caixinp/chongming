"""
Worker 入口
============

启动 Worker 应用，加载所有业务模块。

使用步骤：
  1. 编写 handler：在 ``app/handlers/`` 下新建文件，用 ``@app.handler("subject")`` 注册
  2. 注册模块：在 ``app/handlers/__init__.py`` 中 import 新建的模块
  3. 启动：直接运行本文件

Handler 参数注入规则：
  - 业务参数（user_id, a, b 等）→ 客户端传入 JSON 字段映射
  - 框架保留参数（``_app``, ``_nc``）→ 框架自动注入，无需客户端传入
"""

from app.bootstrap import app
from app.handlers import *

def main():
    # 启动 Worker（自动处理：NATS 连接 → 服务注册 → 心跳 → 优雅关闭）
    app.run()


if __name__ == "__main__":
    main()
