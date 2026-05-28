import os
import nats

nc = None

def _get_nats_urls() -> list[str]:
    """从环境变量 NATS_SERVERS 或配置文件获取 NATS 服务器地址"""
    env_urls = os.environ.get("NATS_SERVERS")
    if env_urls:
        return [url.strip() for url in env_urls.split(",") if url.strip()]

    try:
        from chongming_config import load_gateway_config
        config = load_gateway_config("config.toml")
        urls = config.get("nats", {}).get("urls", [])
        if urls:
            return urls
    except Exception:
        pass

    return ["nats://localhost:4222", "nats://localhost:4223", "nats://localhost:4224"]


async def get_nats_client() -> nats.NATS: # type: ignore
    global nc
    if nc is None:
        urls = _get_nats_urls()
        nc = await nats.connect(urls)
    return nc
