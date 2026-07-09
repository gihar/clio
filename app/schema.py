"""DDL, миграции и инициализация схемы БД."""

import logging

from .database import get_cursor

logger = logging.getLogger(__name__)


# SQL для создания таблиц
CREATE_TABLES_SQL = """
-- Таблица чатов
CREATE TABLE IF NOT EXISTS chats (
    id BIGINT PRIMARY KEY,
    type VARCHAR(255) NOT NULL,
    title TEXT,
    username VARCHAR(255),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    is_bot BOOLEAN NOT NULL,
    first_name TEXT,
    last_name TEXT,
    username VARCHAR(255),
    language_code VARCHAR(10),
    is_premium BOOLEAN DEFAULT FALSE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Таблица сообщений (расширенная)
CREATE TABLE IF NOT EXISTS messages (
    message_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    user_id BIGINT,
    message_type VARCHAR(50) NOT NULL DEFAULT 'text',
    text TEXT,
    caption TEXT,
    reply_to_message_id BIGINT,
    forward_from_chat_id BIGINT,
    sent_at TIMESTAMPTZ NOT NULL,
    edited_at TIMESTAMPTZ,
    raw_message JSONB,

    PRIMARY KEY (chat_id, message_id),
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- Таблица заявок на вступление (для авто-отклонения "свежих" аккаунтов)
CREATE TABLE IF NOT EXISTS join_requests (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    username VARCHAR(255),
    first_name TEXT,
    bio TEXT,
    request_date TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_join_requests_user_chat UNIQUE (user_id, chat_id),
    CONSTRAINT ck_join_requests_status CHECK (status IN ('pending','declined','expired')),
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Таблица спам-пометок: юзеры, которых антиспам-бот замутил намертво.
-- Их сообщения исключаются из аналитических выборок (дайджест/стратегия).
CREATE TABLE IF NOT EXISTS spam_users (
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    muted_at TIMESTAMPTZ NOT NULL,
    muted_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (chat_id, user_id),
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Индексы для оптимизации запросов (кроме message_type - создаётся после миграций)
CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_sent_at ON messages(sent_at);
CREATE INDEX IF NOT EXISTS idx_chats_username ON chats(username) WHERE username IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username) WHERE username IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_join_requests_chat_status ON join_requests(chat_id, status);
CREATE INDEX IF NOT EXISTS idx_join_requests_user_id ON join_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_join_requests_request_date ON join_requests(request_date);
"""

# SQL для миграции существующих таблиц
MIGRATION_SQL = """
-- Добавляем новые колонки, если их нет
DO $$ 
BEGIN
    -- messages: message_type
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='messages' AND column_name='message_type') THEN
        ALTER TABLE messages ADD COLUMN message_type VARCHAR(50) NOT NULL DEFAULT 'text';
    END IF;
    
    -- messages: caption
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='messages' AND column_name='caption') THEN
        ALTER TABLE messages ADD COLUMN caption TEXT;
    END IF;
    
    -- messages: reply_to_message_id
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='messages' AND column_name='reply_to_message_id') THEN
        ALTER TABLE messages ADD COLUMN reply_to_message_id BIGINT;
    END IF;
    
    -- messages: forward_from_chat_id
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='messages' AND column_name='forward_from_chat_id') THEN
        ALTER TABLE messages ADD COLUMN forward_from_chat_id BIGINT;
    END IF;
    
    -- messages: edited_at
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='messages' AND column_name='edited_at') THEN
        ALTER TABLE messages ADD COLUMN edited_at TIMESTAMPTZ;
    END IF;
    
    -- users: is_premium
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='is_premium') THEN
        ALTER TABLE users ADD COLUMN is_premium BOOLEAN DEFAULT FALSE;
    END IF;
    
    -- users: last_updated_at
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='last_updated_at') THEN
        ALTER TABLE users ADD COLUMN last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
    END IF;
END $$;

-- Создаём индекс для message_type если его нет
CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(message_type);
"""


async def create_tables():
    """Создает таблицы в базе данных."""
    async with get_cursor() as cur:
        await cur.execute(CREATE_TABLES_SQL)
        logger.info("Database tables created/verified")


async def run_migrations():
    """Запускает миграции для обновления схемы."""
    async with get_cursor() as cur:
        await cur.execute(MIGRATION_SQL)
        logger.info("Database migrations completed")


async def init_database():
    """Инициализирует базу данных: создаёт таблицы и запускает миграции."""
    # Сначала создаём базовые таблицы
    await create_tables()
    # Затем запускаем миграции (добавляют новые колонки)
    await run_migrations()
    # Создаём индекс на message_type после миграций
    async with get_cursor() as cur:
        await cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(message_type);")
        logger.info("Message type index created/verified")
