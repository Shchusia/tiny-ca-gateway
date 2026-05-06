from fastapi import FastAPI

from tiny_ca_gateway.core.base_manager import BaseCAManager


class FastAPILifespanManager(BaseCAManager):
    _logger_name = "fastapi-ca"
