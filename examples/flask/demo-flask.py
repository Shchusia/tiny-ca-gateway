"""
example_flask_ca/demo-aiohttp.py
~~~~~~~~~~~~~~~~~~~~~~~~
Flask + tiny-ca + Swagger UI.

Swagger UI:   http://localhost:8000/docs
OpenAPI JSON: http://localhost:8000/openapi.json
"""

from __future__ import annotations
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
import json
import logging

from flask import Flask, Response, jsonify
from tiny_ca_gateway.flask.api.v1.ca_blueprint import ca_bp
from tiny_ca_gateway.flask.lifespan.manager import FlaskCAManager
from tiny_ca_gateway.openapi import SWAGGER_UI_HTML, build_openapi_schema

logging.basicConfig(
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
LOGGER = logging.getLogger("flask-ca")


def create_app() -> Flask:
    app = Flask(__name__)

    FlaskCAManager(
        logger=LOGGER, common_name="Flask Root CA", organization="ACME Corp"
    ).init_sync()

    app.register_blueprint(ca_bp, url_prefix="/api/v1/ca")

    @app.get("/openapi.json")
    def openapi_schema():
        return Response(
            json.dumps(
                build_openapi_schema(title="Tiny CA API (Flask)", version="1.0"),
                default=str,
            ),
            content_type="application/json",
        )

    @app.get("/docs")
    def swagger_ui():
        return Response(
            SWAGGER_UI_HTML.format(
                title="Tiny CA API (Flask)", openapi_url="/openapi.json"
            ),
            content_type="text/html",
        )

    @app.errorhandler(404)
    def not_found(e):
        return jsonify(detail=str(e)), 404

    @app.errorhandler(500)
    def internal_error(e):
        LOGGER.error("Unhandled: %s", e, exc_info=True)
        return jsonify(detail="Internal server error"), 500

    @app.get("/health")
    def health():
        return jsonify(status="ok", framework="flask")

    return app


app = create_app()
if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8000, debug=True)
