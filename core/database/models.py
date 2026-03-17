"""SQLAlchemy ORM models for multi-tenant Bob."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import DeclarativeBase, relationship


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="tenant", cascade="all, delete-orphan")
    agent_runs = relationship("AgentRun", back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_tenant_email"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)
    is_approved = Column(Boolean, default=False, nullable=False)
    verification_token = Column(String(255), nullable=True)
    reset_token = Column(String(255), nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="users")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    agent_runs = relationship("AgentRun", back_populates="user", cascade="all, delete-orphan")
    api_tokens = relationship("ApiToken", back_populates="user", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=True)
    is_expired = Column(Boolean, default=False, nullable=False)
    summary = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="conversations")
    user = relationship("User", back_populates="conversations")
    turns = relationship("ConversationTurn", back_populates="conversation", cascade="all, delete-orphan", order_by="ConversationTurn.created_at")


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id = Column(String(36), primary_key=True, default=_uuid)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_message = Column(Text, nullable=False)
    assistant_message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    conversation = relationship("Conversation", back_populates="turns")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    task = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    output = Column(Text, nullable=True)
    steps_json = Column(JSON, default=list)
    tool_calls_json = Column(JSON, default=list)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    tenant = relationship("Tenant", back_populates="agent_runs")
    user = relationship("User", back_populates="agent_runs")


class EmailAccount(Base):
    """Email account — Gmail (OAuth) or generic IMAP/SMTP (per user, multi-tenant)."""
    __tablename__ = "email_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "email_address", name="uq_user_provider_email"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(20), nullable=False, default="gmail")  # gmail | imap
    email_address = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)  # friendly name shown in sidebar

    # OAuth fields (Gmail)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    scopes = Column(Text, nullable=True)

    # IMAP/SMTP fields (generic email)
    imap_host = Column(String(255), nullable=True)
    imap_port = Column(Integer, nullable=True, default=993)
    smtp_host = Column(String(255), nullable=True)
    smtp_port = Column(Integer, nullable=True, default=465)
    imap_password = Column(Text, nullable=True)  # stored for IMAP/SMTP auth

    is_active = Column(Boolean, default=True, nullable=False)
    last_sync_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    user = relationship("User")
    tenant = relationship("Tenant")


class EmailDigest(Base):
    """Processed email — triaged by LLM."""
    __tablename__ = "email_digests"
    __table_args__ = (
        Index("ix_email_digests_user_status", "user_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(String(36), ForeignKey("email_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    message_id = Column(String(255), nullable=False, unique=True, index=True)
    source = Column(String(20), nullable=False, default="gmail")
    sender = Column(String(500), nullable=False)
    subject = Column(String(1000), nullable=True)
    body_snippet = Column(Text, nullable=True)
    attachments_json = Column(JSON, default=list)
    urgency = Column(String(10), nullable=False, default="medium")
    category = Column(String(50), nullable=True)
    action = Column(Text, nullable=True)
    reply_draft = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    received_at = Column(DateTime, nullable=True)
    processed_at = Column(DateTime, default=_utcnow, nullable=False)

    tenant = relationship("Tenant")
    user = relationship("User")


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    token_prefix = Column(String(8), nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    user = relationship("User", back_populates="api_tokens")
    tenant = relationship("Tenant")


class Contact(Base):
    """Known email contact — auto-extracted from emails or manually added via chat.

    Contacts are permanent and never auto-deleted.
    """
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("user_id", "email", name="uq_user_contact_email"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False)
    name = Column(String(255), nullable=True)
    source = Column(String(20), nullable=False, default="email")  # email | chat | manual
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    user = relationship("User")
    tenant = relationship("Tenant")
