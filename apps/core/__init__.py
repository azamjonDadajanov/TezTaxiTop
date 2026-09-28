"""Shared technical layer.

This package contains **no business models**. It only hosts cross-cutting
concerns that every domain application needs:

* :mod:`apps.core.models`      - abstract ``TimeStampedModel`` base class
* :mod:`apps.core.conf`        - typed access to business-rule settings
* :mod:`apps.core.exceptions`  - the business exception hierarchy
* :mod:`apps.core.exception_handler` - DRF mapping of those exceptions
* :mod:`apps.core.permissions` - reusable object level permission classes
* :mod:`apps.core.pagination` / :mod:`apps.core.throttling`
* :mod:`apps.core.validators`  - shared field validators

The domain architecture (``users``, ``rides``, ``orders`` ...) is unchanged.
"""
