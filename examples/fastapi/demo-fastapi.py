import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from logging import Logger, getLogger

from fastapi import FastAPI
from pydantic_settings import BaseSettings
from contextlib import asynccontextmanager
from tiny_ca_gateway.fastapi.api.v1 import ca_router
from tiny_ca_gateway.fastapi.lifespan.manager import FastAPILifespanManager


LOGGER = getLogger("demo-route-api-ca")


@asynccontextmanager
async def lifespan(app: FastAPI):
    lifespan_app_manager = FastAPILifespanManager(logger=LOGGER)

    await lifespan_app_manager.on_startup()
    yield
    await lifespan_app_manager.on_shutdown()


app = FastAPI(lifespan=lifespan)

app.include_router(ca_router, prefix="/api/v1")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("demo-fastapi:app", host="0.0.0.0", port=8000, reload=True, workers=1)
