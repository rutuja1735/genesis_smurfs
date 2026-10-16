"""Reviewed risk classifications for common AgentDojo side-effecting tools."""

WRITE_TOOLS = {
    "send_money", "schedule_transaction", "update_scheduled_transaction", "update_password",
    "update_user_info", "send_email", "delete_email", "send_message", "send_direct_message",
    "send_channel_message", "invite_user", "remove_user", "add_user", "post_webpage",
    "reserve_hotel", "reserve_flight", "cancel_reservation", "create_file", "edit_file",
}

# Read permissions are deliberately explicit and conservative. Unknown tools fail closed.
READ_TOOLS = {
    "get_balance", "get_iban", "get_most_recent_transactions", "get_scheduled_transactions",
    "read_file", "list_files", "search_emails", "read_email", "list_inbox", "get_email",
    "get_channels", "read_channel_messages", "read_inbox", "get_users_in_channel",
    "get_webpage", "search_web", "get_user_info", "get_contacts", "get_calendar_events",
    "search_calendar_events", "get_flight_info", "get_hotel_info", "search_hotels", "search_flights",
}
