import bcrypt


def get_password_hash(password: str) -> str:
    """
    对明文密码进行哈希加密

    使用bcrypt算法对密码进行加盐哈希处理,确保密码存储的安全性。

    Args:
        password: 需要加密的明文密码字符串

    Returns:
        加密后的密码哈希字符串,采用UTF-8编码
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证明文密码与哈希密码是否匹配

    将明文密码与已存储的哈希密码进行比对,用于用户登录时的密码验证。

    Args:
        plain_password: 用户输入的明文密码
        hashed_password: 数据库中存储的哈希密码

    Returns:
        密码匹配返回True,否则返回False
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )
