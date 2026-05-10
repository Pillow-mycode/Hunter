"""
数据库管理模块 - 使用 SQLite 持久化存储会话和消息

设计原则：
1. 所有消息按 order_index 严格排序，确保顺序一致性
2. 每个会话独立管理，互不影响
3. 服务端重启后数据完整保留
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import threading


class DatabaseManager:
    """SQLite 数据库管理器"""

    def __init__(self, db_path: str = None):
        """
        初始化数据库管理器

        Args:
            db_path: 数据库文件路径，默认为项目根目录下的 data/hunter.db
        """
        if db_path is None:
            # 默认存储在项目根目录的 data 文件夹下
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            data_dir = os.path.join(project_root, 'data')
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, 'hunter.db')

        self.db_path = db_path
        self._local = threading.local()
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接"""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection

    @contextmanager
    def _get_cursor(self):
        """获取数据库游标的上下文管理器"""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    def _init_database(self):
        """初始化数据库表结构"""
        with self._get_cursor() as cursor:
            # 会话表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT DEFAULT 'idle',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 消息表 - 核心表，存储所有交互记录
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    msg_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    order_index INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            ''')

            # Agent 间通信消息表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS agent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    msg_id TEXT UNIQUE NOT NULL,
                    sender TEXT NOT NULL,
                    receiver TEXT NOT NULL,
                    msg_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    context_json TEXT,
                    expect_reply INTEGER DEFAULT 0,
                    reply_to TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            ''')

            # Blackboard 快照表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blackboard_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            ''')

            # 创建索引以加速查询
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_session_order
                ON messages(session_id, order_index)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_session_id
                ON messages(session_id)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_agent_messages_session_id
                ON agent_messages(session_id)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_blackboard_snapshots_session_id
                ON blackboard_snapshots(session_id)
            ''')

    # ==================== 会话管理 ====================

    def create_session(self, session_id: str, name: str) -> Dict[str, Any]:
        """
        创建新会话

        Args:
            session_id: 会话ID
            name: 会话名称

        Returns:
            会话信息字典
        """
        now = datetime.now().isoformat()
        with self._get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO sessions (id, name, status, created_at, updated_at)
                VALUES (?, ?, 'idle', ?, ?)
            ''', (session_id, name, now, now))

        return {
            'id': session_id,
            'name': name,
            'status': 'idle',
            'created_at': now,
            'updated_at': now
        }

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话信息

        Args:
            session_id: 会话ID

        Returns:
            会话信息字典，不存在则返回 None
        """
        with self._get_cursor() as cursor:
            cursor.execute('SELECT * FROM sessions WHERE id = ?', (session_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        获取所有会话列表（按创建时间倒序）

        Returns:
            会话列表
        """
        with self._get_cursor() as cursor:
            cursor.execute('SELECT * FROM sessions ORDER BY created_at DESC')
            return [dict(row) for row in cursor.fetchall()]

    def update_session_status(self, session_id: str, status: str):
        """
        更新会话状态

        Args:
            session_id: 会话ID
            status: 新状态 (idle, running, need_input, need_confirm)
        """
        now = datetime.now().isoformat()
        with self._get_cursor() as cursor:
            cursor.execute('''
                UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?
            ''', (status, now, session_id))

    def delete_session(self, session_id: str):
        """
        删除会话及其所有消息

        Args:
            session_id: 会话ID
        """
        with self._get_cursor() as cursor:
            cursor.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM agent_messages WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM blackboard_snapshots WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM sessions WHERE id = ?', (session_id,))

    # ==================== 消息管理 ====================

    def add_message(self, session_id: str, msg_type: str, content: str,
                    metadata: Dict[str, Any] = None) -> int:
        """
        添加消息到会话

        Args:
            session_id: 会话ID
            msg_type: 消息类型 (user, progress, command, assistant, confirm, input, file, error)
            content: 消息内容
            metadata: 额外元数据（可选）

        Returns:
            新消息的 order_index
        """
        with self._get_cursor() as cursor:
            # 获取当前会话的最大 order_index
            cursor.execute('''
                SELECT COALESCE(MAX(order_index), -1) as max_order
                FROM messages WHERE session_id = ?
            ''', (session_id,))
            max_order = cursor.fetchone()['max_order']
            new_order = max_order + 1

            # 插入新消息
            metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
            cursor.execute('''
                INSERT INTO messages (session_id, msg_type, content, metadata, order_index, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (session_id, msg_type, content, metadata_json, new_order, datetime.now().isoformat()))

            return new_order

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """
        获取会话的所有消息（按 order_index 排序）

        Args:
            session_id: 会话ID

        Returns:
            消息列表，严格按顺序排列
        """
        with self._get_cursor() as cursor:
            cursor.execute('''
                SELECT * FROM messages
                WHERE session_id = ?
                ORDER BY order_index ASC
            ''', (session_id,))

            messages = []
            for row in cursor.fetchall():
                msg = dict(row)
                # 解析 metadata JSON
                if msg['metadata']:
                    try:
                        msg['metadata'] = json.loads(msg['metadata'])
                    except json.JSONDecodeError:
                        msg['metadata'] = None
                messages.append(msg)

            return messages

    def get_message_count(self, session_id: str) -> int:
        """
        获取会话的消息数量

        Args:
            session_id: 会话ID

        Returns:
            消息数量
        """
        with self._get_cursor() as cursor:
            cursor.execute('SELECT COUNT(*) as count FROM messages WHERE session_id = ?', (session_id,))
            return cursor.fetchone()['count']

    def get_last_message(self, session_id: str, msg_type: str = None) -> Optional[Dict[str, Any]]:
        """
        获取会话的最后一条消息

        Args:
            session_id: 会话ID
            msg_type: 可选，指定消息类型

        Returns:
            最后一条消息，不存在则返回 None
        """
        with self._get_cursor() as cursor:
            if msg_type:
                cursor.execute('''
                    SELECT * FROM messages
                    WHERE session_id = ? AND msg_type = ?
                    ORDER BY order_index DESC LIMIT 1
                ''', (session_id, msg_type))
            else:
                cursor.execute('''
                    SELECT * FROM messages
                    WHERE session_id = ?
                    ORDER BY order_index DESC LIMIT 1
                ''', (session_id,))

            row = cursor.fetchone()
            if row:
                msg = dict(row)
                if msg['metadata']:
                    try:
                        msg['metadata'] = json.loads(msg['metadata'])
                    except json.JSONDecodeError:
                        msg['metadata'] = None
                return msg
        return None

    def clear_messages(self, session_id: str):
        """
        清空会话的所有消息

        Args:
            session_id: 会话ID
        """
        with self._get_cursor() as cursor:
            cursor.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))

    # ==================== 对话历史（用于 LLM）====================

    def get_conversation_history(self, session_id: str) -> List[Dict[str, str]]:
        """
        获取会话的对话历史（仅 user 和 assistant 消息，用于 LLM 上下文）

        Args:
            session_id: 会话ID

        Returns:
            对话历史列表，格式为 [{"role": "user/assistant", "content": "..."}]
        """
        with self._get_cursor() as cursor:
            cursor.execute('''
                SELECT msg_type, content FROM messages
                WHERE session_id = ? AND msg_type IN ('user', 'assistant')
                ORDER BY order_index ASC
            ''', (session_id,))

            history = []
            for row in cursor.fetchall():
                role = 'user' if row['msg_type'] == 'user' else 'assistant'
                history.append({
                    'role': role,
                    'content': row['content']
                })

            return history

    # ==================== Agent 间消息 ====================

    def save_agent_message(self, msg: dict) -> int:
        with self._get_cursor() as cursor:
            context_json = None
            if msg.get('context_json'):
                context_json = json.dumps(msg['context_json'], ensure_ascii=False)

            cursor.execute('''
                INSERT INTO agent_messages
                    (session_id, msg_id, sender, receiver, msg_type, content,
                     context_json, expect_reply, reply_to)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                msg.get('session_id', ''),
                msg.get('msg_id', ''),
                msg.get('sender', ''),
                msg.get('receiver', ''),
                msg.get('msg_type', ''),
                msg.get('content', ''),
                context_json,
                1 if msg.get('expect_reply') else 0,
                msg.get('reply_to'),
            ))
            return cursor.lastrowid

    def get_agent_messages(self, session_id: str, limit: int = 100) -> list:
        with self._get_cursor() as cursor:
            cursor.execute('''
                SELECT * FROM agent_messages
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (session_id, limit))

            messages = []
            for row in cursor.fetchall():
                msg = dict(row)
                if msg['context_json']:
                    try:
                        msg['context_json'] = json.loads(msg['context_json'])
                    except json.JSONDecodeError:
                        msg['context_json'] = None
                messages.append(msg)

            return messages

    # ==================== Blackboard 快照 ====================

    def save_blackboard_snapshot(self, session_id: str, snapshot: dict) -> int:
        with self._get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO blackboard_snapshots (session_id, snapshot_json)
                VALUES (?, ?)
            ''', (session_id, json.dumps(snapshot, ensure_ascii=False)))
            return cursor.lastrowid

    def get_latest_snapshot(self, session_id: str) -> Optional[dict]:
        with self._get_cursor() as cursor:
            cursor.execute('''
                SELECT * FROM blackboard_snapshots
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            ''', (session_id,))

            row = cursor.fetchone()
            if row:
                return json.loads(row['snapshot_json'])
            return None

    # ==================== 统计信息 ====================

    def get_stats(self) -> Dict[str, Any]:
        """
        获取数据库统计信息

        Returns:
            统计信息字典
        """
        with self._get_cursor() as cursor:
            cursor.execute('SELECT COUNT(*) as count FROM sessions')
            session_count = cursor.fetchone()['count']

            cursor.execute('SELECT COUNT(*) as count FROM messages')
            message_count = cursor.fetchone()['count']

            return {
                'session_count': session_count,
                'message_count': message_count,
                'db_path': self.db_path,
                'db_size_kb': os.path.getsize(self.db_path) / 1024 if os.path.exists(self.db_path) else 0
            }

    def close(self):
        """关闭数据库连接"""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None


# 全局单例
_db_instance: Optional[DatabaseManager] = None


def get_database() -> DatabaseManager:
    """获取数据库管理器单例"""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager()
    return _db_instance
