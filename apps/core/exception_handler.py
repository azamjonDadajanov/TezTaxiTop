"""DRF exception handler that maps business errors to clean API responses.

A successful response keeps the standard DRF shape. An expected business error
is rendered as::

    {
        "error": {
            "code": "insufficient_seats",
            "message": "Yetarli bo'sh o'rin mavjud emas.",
            "details": {"available_seats": 0}
        }
    }

Unexpected exceptions are re-raised so that Django's 500 handler / error
reporting keeps working - they are never disguised as business errors.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from apps.core.exceptions import BusinessError

logger = logging.getLogger(__name__)

#: Validation errors raised by model ``clean()`` methods.
_HTTP_400 = status.HTTP_400_BAD_REQUEST


def _flatten_django_validation_error(error: DjangoValidationError) -> dict[str, Any]:
    """Convert ``message_dict``/``messages`` into a JSON friendly structure."""
    if hasattr(error, "message_dict"):
        return {key: [str(item) for item in value] for key, value in error.message_dict.items()}
    return {"non_field_errors": [str(item) for item in error.messages]}


def business_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF ``EXCEPTION_HANDLER`` that understands :class:`BusinessError`."""
    if isinstance(exc, BusinessError):
        return Response(
            data={"error": exc.as_dict()},
            status=exc.status_code,
        )

    if isinstance(exc, DjangoValidationError):
        return Response(
            data={"error": {"code": "validation_error", "message": str(exc), "details": _flatten_django_validation_error(exc)}},
            status=_HTTP_400,
        )

    if isinstance(exc, Http404):
        return Response(
            data={"error": {"code": "not_found", "message": "So'ralgan ma'lumot topilmadi."}},
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, DjangoPermissionDenied):
        return Response(
            data={"error": {"code": "permission_denied", "message": "Ruxsat berilmadi."}},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Anything else is either a DRF exception (ValidationError, NotFound, ...)
    # or a genuine bug that must keep bubbling up.
    response = drf_exception_handler(exc, context)
    if response is not None and isinstance(response.data, dict) and "detail" in response.data:
        detail = response.data["detail"]
        response.data = {
            "error": {
                "code": getattr(detail, "code", None) or "error",
                "message": str(detail),
            }
        }
    return response
