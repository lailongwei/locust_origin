import logging
from .. import events
from ..env import Environment

"""teddy扩展专用logger"""
teddy_logger = logging.getLogger('locust.teddy')
network_logger = logging.getLogger('locust.network')
