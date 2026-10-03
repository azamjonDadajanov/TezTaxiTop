"""URL configuration for the chat app."""

from __future__ import annotations

from django.urls import path

from apps.chat import views

app_name = "chat"

urlpatterns = [
    path("chats/", views.ChatThreadListView.as_view(), name="thread-list"),
    path("chats/open/", views.OpenChatView.as_view(), name="open-chat"),
    path("chats/<int:order_id>/messages/", views.ChatMessageView.as_view(), name="message-list"),
    path("chats/<int:order_id>/read/", views.ChatReadView.as_view(), name="mark-read"),
]
