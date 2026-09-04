"""
audio2video.ssl_ctx — Shared SSL context backed by certifi.

Python framework builds (e.g. /Library/Frameworks/Python.framework) often ship
without a configured CA bundle, causing `SSL: CERTIFICATE_VERIFY_FAILED` on all
urllib HTTPS calls. This module builds an ssl.SSLContext from certifi and also
exports SSL_CERT_FILE so other HTTP clients (httpx/Gemini) inherit it.
"""

import os
import ssl

_SSL_CONTEXT = None


def get_ssl_context() -> ssl.SSLContext:
    """Return a cached default SSL context with certifi CA certs loaded."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        try:
            import certifi
            _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
            os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        except ImportError:
            _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT