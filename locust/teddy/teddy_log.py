import logging
from .. import events
from ..env import Environment

"""teddy扩展专用logger"""
teddy_logger = logging.getLogger('teddy')


@events.init.add_listener
def _init_teddy_logger(environment: Environment, runner, web_ui):
    """Locust初始化处理器, 用于读取选项并设置teddy logger日志级别"""
    teddy_loglv = environment.parsed_options.teddy_loglevel.upper()
    if teddy_loglv in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        teddy_logger.setLevel(getattr(logging, teddy_loglv))
