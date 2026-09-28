"""Notifications application: in-app notification centre.

The notification system is **independent of Telegram**. A service call always
creates a database record first; delivering that record to Telegram (or any
other channel) is the job of a Celery task that reads ``sent_at is null`` rows.
That keeps the domain layer free of Telegram specifics and makes the platform
usable from a web frontend, a Mini App or a mobile app without changes.
"""

default_app_config = "apps.notifications.apps.NotificationsConfig"
