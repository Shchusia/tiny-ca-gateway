from enum import StrEnum


class Routes(StrEnum):
    # Public
    GET_PUBLIC_CERT = "/cert"
    BASE_CRL = "/crl"

    # Lists
    GET_LIST_CERTS = ""
    GET_LIST_EXPIRING_CERTS = "/expiring"

    # CA bootstrap
    CA_ROOT = "/root"
    CA_INTERMEDIATE = "/intermediate"

    # Issuance
    ISSUE = "/issue"

    # File downloads
    DOWNLOAD = "/{uuid_certificate}"
    DOWNLOAD_STREAM = "/stream/{uuid_certificate}"

    # Maintenance
    MAINTENANCE_EXPIRE = "/maintenance/expire"

    # CRL
    CRL_REFRESH = "/crl/refresh"
    CRL_VERIFY = "/crl/verify"

    # Operations
    VERIFY = "/verify"
    COSIGN = "/cosign"
    EXPORT = "/export-p12/{serial}"
    REVOKE = "/revoke"
    ROTATE = "/rotate/{serial}"
    RENEW = "/renew/{serial}"
    DELETE = "/{serial}"
    STATUS = "/status/{serial}"
    INSPECT = "/inspect/{serial}"
    CHAIN = "/chain/{serial}"
