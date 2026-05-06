from django.urls import path
from ninja import NinjaAPI
from ninja.errors import HttpError
from django.http import JsonResponse

from tiny_ca_gateway.django.api.v1.ca_router import ca_router


api = NinjaAPI(
    title="Tiny CA API",
    version="1.0",
    description=(
        "Certificate Authority REST API.\n\n"
        "**Public endpoints** (without token): `GET /ca/cert`, `GET /ca/crl`\n\n"
        "**Others** require the header: `Authorization: Bearer <token>`"
    ),
    docs_url="/docs",
    openapi_url="/openapi.json",
)


api.add_router("/ca", ca_router)


# ---------------------------------------------------------------------------
# Global error handler
# ---------------------------------------------------------------------------


@api.exception_handler(HttpError)
def http_error_handler(request, exc: HttpError):
    return JsonResponse({"detail": str(exc)}, status=exc.status_code)


@api.exception_handler(Exception)
def unhandled_error_handler(request, exc: Exception):
    import logging

    logging.getLogger("django-ca").error("Unhandled error: %s", exc, exc_info=True)
    return JsonResponse({"detail": "Internal server error"}, status=500)


# ---------------------------------------------------------------------------
# URL patterns
# ---------------------------------------------------------------------------

urlpatterns = [
    path("api/v1/", api.urls),
]
