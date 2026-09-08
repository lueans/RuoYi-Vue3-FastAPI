import uvicorn

from config.env import AppConfig
from server import create_app

if __name__ != '__main__':
    app = create_app()

if __name__ == '__main__':
    uvicorn.run(
        app='server:create_app',
        host=AppConfig.app_host,
        port=AppConfig.app_port,
        root_path=AppConfig.app_root_path,
        reload=AppConfig.app_reload,
        workers=AppConfig.app_workers,
        factory=True,
        # utils.log_util 已统一接管标准 logging，并在写出前脱敏分享
        # token 等凭证。Uvicorn 的默认 log_config 会在这里重新覆盖
        # uvicorn.access handler，导致原始请求路径绕过脱敏直接输出。
        log_config=None,
    )
