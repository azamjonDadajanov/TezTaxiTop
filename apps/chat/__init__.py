"""Chat application: order-scoped driver <-> passenger messaging.

Design decisions
----------------
* A thread is created **for an order**, not for two arbitrary users. This makes
  the authorization rule trivial: only the driver and the passengers of that
  order may read or write the thread.
* Every message row stores ``is_read``/``read_at`` for the reader, therefore a
  thread needs **no separate read-receipt table** and unread counts are a plain
  aggregate.
* Delivery is polling based (``GET /chats/<order_id>/messages/?after=<id>``),
  which is why messages are ordered by an auto-incrementing primary key and
  every response carries the newest message id as the next ``after`` cursor.
"""

default_app_config = "apps.chat.apps.ChatConfig"
