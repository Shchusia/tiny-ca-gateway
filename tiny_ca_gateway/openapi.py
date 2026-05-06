from __future__ import annotations

from typing import Any


def build_openapi_schema(
    title: str = "Tiny CA API", version: str = "1.0"
) -> dict[str, Any]:
    import json

    from pydantic import TypeAdapter

    from tiny_ca_gateway.core.schemas import (
        CertListItem,
        ChainResponse,
        CosignRequest,
        CosignResponse,
        CreateRootCaResponse,
        CRLRefreshResponse,
        CRLVerifyRequest,
        DeleteResponse,
        ExpiringResponse,
        ExportP12Request,
        IntermediateCARequest,
        IssueCertRequest,
        IssueCertResponse,
        MaintenanceResponse,
        RenewRequest,
        RenewResponse,
        RevokeRequest,
        RevokeResponse,
        RotateResponse,
        StatusResponse,
        VerifyRequest,
        VerifyResponse,
    )

    def schema(model: Any) -> dict[str, Any]:
        return TypeAdapter(model).json_schema()

    all_models = [
        CertListItem,
        ExpiringResponse,
        CreateRootCaResponse,
        IssueCertResponse,
        MaintenanceResponse,
        VerifyResponse,
        CRLRefreshResponse,
        RevokeResponse,
        DeleteResponse,
        StatusResponse,
        RenewResponse,
        CosignResponse,
        ChainResponse,
        RotateResponse,
        IntermediateCARequest,
        IssueCertRequest,
        CRLVerifyRequest,
        VerifyRequest,
        CosignRequest,
        ExportP12Request,
        RevokeRequest,
        RenewRequest,
    ]

    components: dict[str, Any] = {}
    for m in all_models:
        s = schema(m)
        components[m.__name__] = s

    def ref(name: str) -> dict[str, Any]:
        return {"$ref": f"#/components/schemas/{name}"}

    def body(name: str) -> dict[str, Any]:
        return {
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": ref(name)}},
            }
        }

    def resp(name: str, status: int = 200) -> dict[str, Any]:
        return {
            str(status): {
                "description": "OK",
                "content": {"application/json": {"schema": ref(name)}},
            },
            "4XX": {
                "description": "Client error",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorDetail"}
                    }
                },
            },
        }

    def resp_raw(description: str = "Binary file") -> dict[str, Any]:
        return {
            "200": {
                "description": description,
                "content": {
                    "application/x-pem-file": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                },
            }
        }

    bearer: list[dict[str, Any]] = [{"BearerAuth": []}]

    paths: dict[str, Any] = {
        # ------------------------------------------------------------------
        # Public
        # ------------------------------------------------------------------
        "/api/v1/ca/cert": {
            "get": {
                "tags": ["Public"],
                "summary": "Download CA public certificate",
                "responses": resp_raw("PEM certificate"),
            }
        },
        "/api/v1/ca/crl": {
            "get": {
                "tags": ["Public"],
                "summary": "Download CRL",
                "parameters": [
                    {
                        "name": "pem",
                        "in": "query",
                        "schema": {"type": "boolean", "default": False},
                    }
                ],
                "responses": resp_raw("CRL file"),
            }
        },
        # ------------------------------------------------------------------
        # List
        # ------------------------------------------------------------------
        "/api/v1/ca/": {
            "get": {
                "tags": ["Certificates"],
                "summary": "List certificates",
                "security": bearer,
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "schema": {
                            "type": "string",
                            "enum": ["valid", "revoked", "expired"],
                        },
                    },
                    {"name": "key_type", "in": "query", "schema": {"type": "string"}},
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {
                            "type": "integer",
                            "default": 100,
                            "minimum": 1,
                            "maximum": 1000,
                        },
                    },
                    {
                        "name": "offset",
                        "in": "query",
                        "schema": {"type": "integer", "default": 0, "minimum": 0},
                    },
                ],
                "responses": {
                    "200": {
                        "description": "OK",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": ref("CertListItem"),
                                }
                            }
                        },
                    }
                },
            }
        },
        "/api/v1/ca/expiring": {
            "get": {
                "tags": ["Certificates"],
                "summary": "Certificates expiring soon",
                "security": bearer,
                "parameters": [
                    {
                        "name": "within_days",
                        "in": "query",
                        "schema": {
                            "type": "integer",
                            "default": 30,
                            "minimum": 1,
                            "maximum": 365,
                        },
                    }
                ],
                "responses": resp("ExpiringResponse"),
            }
        },
        # ------------------------------------------------------------------
        # CA bootstrap
        # ------------------------------------------------------------------
        "/api/v1/ca/root": {
            "post": {
                "tags": ["CA Bootstrap"],
                "summary": "Bootstrap self-signed root CA",
                "security": bearer,
                **body("CreateRootCaResponse"),  # reuse — CAConfig not in schemas
                "responses": resp("CreateRootCaResponse"),
            }
        },
        "/api/v1/ca/intermediate": {
            "post": {
                "tags": ["CA Bootstrap"],
                "summary": "Issue intermediate CA",
                "security": bearer,
                **body("IntermediateCARequest"),
                "responses": resp("IssueCertResponse"),
            }
        },
        # ------------------------------------------------------------------
        # Issuance
        # ------------------------------------------------------------------
        "/api/v1/ca/issue": {
            "post": {
                "tags": ["Issuance"],
                "summary": "Issue leaf certificate",
                "security": bearer,
                **body("IssueCertRequest"),
                "responses": resp("IssueCertResponse", 201),
            }
        },
        # ------------------------------------------------------------------
        # Maintenance
        # ------------------------------------------------------------------
        "/api/v1/ca/maintenance/expire": {
            "post": {
                "tags": ["Maintenance"],
                "summary": "Bulk-mark expired certificates",
                "security": bearer,
                "responses": resp("MaintenanceResponse"),
            }
        },
        # ------------------------------------------------------------------
        # CRL
        # ------------------------------------------------------------------
        "/api/v1/ca/crl/refresh": {
            "post": {
                "tags": ["CRL"],
                "summary": "Force-regenerate CRL",
                "security": bearer,
                "responses": resp("CRLRefreshResponse"),
            }
        },
        "/api/v1/ca/crl/verify": {
            "post": {
                "tags": ["CRL"],
                "summary": "Verify CRL signature",
                "security": bearer,
                **body("CRLVerifyRequest"),
                "responses": resp("VerifyResponse"),
            }
        },
        # ------------------------------------------------------------------
        # Verification
        # ------------------------------------------------------------------
        "/api/v1/ca/verify": {
            "post": {
                "tags": ["Verification"],
                "summary": "Verify certificate (chain + revocation)",
                "security": bearer,
                **body("VerifyRequest"),
                "responses": resp("VerifyResponse"),
            }
        },
        "/api/v1/ca/cosign": {
            "post": {
                "tags": ["Verification"],
                "summary": "Co-sign a third-party certificate",
                "security": bearer,
                **body("CosignRequest"),
                "responses": resp("CosignResponse"),
            }
        },
        # ------------------------------------------------------------------
        # Export
        # ------------------------------------------------------------------
        "/api/v1/ca/export-p12/{serial}": {
            "post": {
                "tags": ["Export"],
                "summary": "Export PKCS#12 (.p12) bundle",
                "security": bearer,
                "parameters": [
                    {
                        "name": "serial",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                **body("ExportP12Request"),
                "responses": {
                    "200": {
                        "description": "PKCS#12 binary",
                        "content": {
                            "application/x-pkcs12": {
                                "schema": {"type": "string", "format": "binary"}
                            }
                        },
                    }
                },
            }
        },
        # ------------------------------------------------------------------
        # Mutations
        # ------------------------------------------------------------------
        "/api/v1/ca/revoke": {
            "patch": {
                "tags": ["Mutations"],
                "summary": "Revoke a certificate",
                "security": bearer,
                **body("RevokeRequest"),
                "responses": resp("RevokeResponse"),
            }
        },
        "/api/v1/ca/rotate/{serial}": {
            "post": {
                "tags": ["Mutations"],
                "summary": "Rotate certificate (revoke + re-issue)",
                "security": bearer,
                "parameters": [
                    {
                        "name": "serial",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                **body("IssueCertRequest"),
                "responses": resp("RotateResponse"),
            }
        },
        "/api/v1/ca/renew/{serial}": {
            "post": {
                "tags": ["Mutations"],
                "summary": "Renew certificate (same key, new validity)",
                "security": bearer,
                "parameters": [
                    {
                        "name": "serial",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                **body("RenewRequest"),
                "responses": resp("RenewResponse"),
            }
        },
        "/api/v1/ca/{serial}": {
            "delete": {
                "tags": ["Mutations"],
                "summary": "Hard-delete certificate",
                "security": bearer,
                "parameters": [
                    {
                        "name": "serial",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": resp("DeleteResponse"),
            }
        },
        # ------------------------------------------------------------------
        # Inspection
        # ------------------------------------------------------------------
        "/api/v1/ca/status/{serial}": {
            "get": {
                "tags": ["Inspection"],
                "summary": "Get lifecycle status",
                "security": bearer,
                "parameters": [
                    {
                        "name": "serial",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": resp("StatusResponse"),
            }
        },
        "/api/v1/ca/inspect/{serial}": {
            "get": {
                "tags": ["Inspection"],
                "summary": "Structured certificate details",
                "security": bearer,
                "parameters": [
                    {
                        "name": "serial",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Certificate details",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }
                },
            }
        },
        "/api/v1/ca/chain/{serial}": {
            "get": {
                "tags": ["Inspection"],
                "summary": "Full PEM certificate chain",
                "security": bearer,
                "parameters": [
                    {
                        "name": "serial",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": resp("ChainResponse"),
            }
        },
        # ------------------------------------------------------------------
        # File downloads
        # ------------------------------------------------------------------
        "/api/v1/ca/stream/{uuid}": {
            "get": {
                "tags": ["Downloads"],
                "summary": "Stream certificate artefact",
                "security": bearer,
                "parameters": [
                    {
                        "name": "uuid",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "object_type",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string", "enum": ["pem", "key", "csr"]},
                    },
                ],
                "responses": resp_raw("Streamed artefact"),
            }
        },
        "/api/v1/ca/{uuid}": {
            "get": {
                "tags": ["Downloads"],
                "summary": "Download certificate artefact",
                "security": bearer,
                "parameters": [
                    {
                        "name": "uuid",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "object_type",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string", "enum": ["pem", "key", "csr"]},
                    },
                ],
                "responses": resp_raw("Artefact file"),
            }
        },
    }

    return {
        "openapi": "3.0.3",
        "info": {
            "title": title,
            "version": version,
            "description": "Certificate Authority REST API powered by tiny-ca.",
        },
        "components": {
            "schemas": {
                "ErrorDetail": {
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
                **components,
            },
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"},
            },
        },
        "paths": paths,
    }


# ---------------------------------------------------------------------------
# Swagger UI HTML
# ---------------------------------------------------------------------------

SWAGGER_UI_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>{title}</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({{
      url: "{openapi_url}",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: "BaseLayout",
      deepLinking: true,
      persistAuthorization: true,
    }})
  </script>
</body>
</html>"""
