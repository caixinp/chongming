from pydantic import BaseModel
from typing import Optional


class Detail(BaseModel):
    """
    HTTP错误详情模型

    用于封装HTTP错误的详细信息，包括错误消息和错误代码。

    Attributes:
        message (str): 错误描述信息
        code (int): 错误状态码或业务错误码
    """

    message: str
    code: int


class HTTPError(BaseModel):
    """
    HTTP错误响应模型

    用于标准化HTTP错误响应的数据结构，符合RESTful API规范。

    Attributes:
        detail (Optional[Detail]): 错误详情对象，包含具体的错误信息和错误码。
                                  如果为None，表示没有详细的错误信息。
    """

    detail: Optional[Detail] = None
