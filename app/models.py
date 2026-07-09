"""Временный re-export shim на время PRD-03 (разделение app/models.py по концепциям).

Функции переехали в app/schema.py, app/ingest.py, app/spam_flags.py,
app/join_requests.py, app/admin_reads.py. Этот файл будет удалён вместе с
обновлением всех импортёров (см. связанный issue). Импортёров напрямую
трогать в этом коммите не нужно — модуль реэкспортирует прежний публичный
интерфейс без изменений.
"""

from .schema import (
    CREATE_TABLES_SQL,
    MIGRATION_SQL,
    create_tables,
    run_migrations,
    init_database,
)
from .ingest import (
    detect_message_type,
    get_forward_chat_id,
    save_user,
    save_chat,
    save_message,
)
from .spam_flags import (
    flag_spam_user,
    unflag_spam_user,
)
from .join_requests import (
    save_join_request_fields,
    get_pending_fresh_join_requests,
    mark_join_requests_status,
    get_join_requests,
)
from .admin_reads import (
    ChatStats,
    Stats,
    DashboardChat,
    get_stats,
    get_chats_with_stats,
    get_chat_by_id,
    get_users,
    get_dashboard_data,
)

__all__ = [
    "CREATE_TABLES_SQL",
    "MIGRATION_SQL",
    "create_tables",
    "run_migrations",
    "init_database",
    "detect_message_type",
    "get_forward_chat_id",
    "save_user",
    "save_chat",
    "save_message",
    "flag_spam_user",
    "unflag_spam_user",
    "save_join_request_fields",
    "get_pending_fresh_join_requests",
    "mark_join_requests_status",
    "get_join_requests",
    "ChatStats",
    "Stats",
    "DashboardChat",
    "get_stats",
    "get_chats_with_stats",
    "get_chat_by_id",
    "get_users",
    "get_dashboard_data",
]
