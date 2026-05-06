"""
tiny_ca_gateway/aiohttp/lifespan/base_manager.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
aiohttp CA manager.
"""

from tiny_ca_gateway.core.base_manager import BaseCAManager


class AiohttpCAManager(BaseCAManager):
    _logger_name = "aiohttp-ca"
