"""
SQLAlchemy models for authentication.

Defines User, AuthToken, and related database models.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, Index, text, JSON
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.dialects.postgresql import UUID

Base = declarative_base()


class User(Base):
    """User model for authentication and profile management."""
    
    __tablename__ = 'users'
    
    # Primary fields
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(30), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    
    # Profile fields
    display_name = Column(String(100), nullable=True)
    full_name = Column(String(255), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    
    # Security fields
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    profile_tier = Column(String(20), default='user', nullable=False)  # user, developer, admin
    email_verified = Column(Boolean, default=False, nullable=False)  # Email verification status
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    last_failed_login_at = Column(DateTime(timezone=True), nullable=True)  # For progressive delay calculation
    
    # Consumption profile
    consumption_profile_id = Column(Integer, ForeignKey('consumption_profiles.id'), nullable=True, index=True)
    
    # OAuth fields
    oauth_provider = Column(String(50), nullable=True, index=True)  # 'google', 'github', 'microsoft', etc.
    oauth_id = Column(String(255), nullable=True)  # Provider's unique user ID
    oauth_metadata = Column(JSON, nullable=True)  # Store additional OAuth profile data
    
    # Relationships
    auth_tokens = relationship("AuthToken", back_populates="user", cascade="all, delete-orphan")
    credentials = relationship("UserCredential", back_populates="user", cascade="all, delete-orphan")
    preferences = relationship("UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user", cascade="all, delete-orphan")
    consumption_profile = relationship("ConsumptionProfile", back_populates="users")
    token_usage = relationship("UserTokenUsage", back_populates="user", cascade="all, delete-orphan")
    oauth_accounts = relationship("OAuthAccount", back_populates="user", cascade="all, delete-orphan")
    
    # Unique constraint for OAuth accounts
    __table_args__ = (
        Index('idx_oauth_provider_id', 'oauth_provider', 'oauth_id', unique=True),
    )
    
    def __repr__(self):
        return f"<User(id='{self.id}', username='{self.username}', email='{self.email}')>"
    
    def to_dict(self, include_sensitive=False):
        """Convert user to dictionary for API responses."""
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
            'is_active': self.is_active,
            'is_admin': self.is_admin,
            'profile_tier': self.profile_tier,
            'consumption_profile_id': self.consumption_profile_id,
            'consumption_profile': self.consumption_profile.to_dict() if self.consumption_profile else None
        }
        
        if include_sensitive:
            data['failed_login_attempts'] = self.failed_login_attempts
            data['locked_until'] = self.locked_until.isoformat() if self.locked_until else None
            data['last_failed_login_at'] = self.last_failed_login_at.isoformat() if self.last_failed_login_at else None
        
        return data


class AuthToken(Base):
    """Authentication token model for session management."""
    
    __tablename__ = 'auth_tokens'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    token_hash = Column(String(255), nullable=False, index=True, unique=True)
    
    # Token metadata
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    
    # Request context
    ip_address = Column(String(45), nullable=True)  # IPv6 max length
    user_agent = Column(String(500), nullable=True)
    
    # Status
    revoked = Column(Boolean, default=False, nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="auth_tokens")
    
    # Indexes
    __table_args__ = (
        Index('idx_token_user_active', 'user_id', 'revoked', 'expires_at'),
    )
    
    def __repr__(self):
        return f"<AuthToken(id='{self.id}', user_id='{self.user_id}', expires_at='{self.expires_at}')>"
    
    def is_valid(self):
        """Check if token is still valid."""
        now = datetime.now(timezone.utc)
        return not self.revoked and self.expires_at > now


class UserCredential(Base):
    """Encrypted credentials storage for user API keys."""
    
    __tablename__ = 'user_credentials'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    provider = Column(String(50), nullable=False)  # Amazon, Google, OpenAI, etc.
    credentials_encrypted = Column(Text, nullable=False)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User", back_populates="credentials")
    
    # Unique constraint: one credential set per user per provider
    __table_args__ = (
        Index('idx_user_provider', 'user_id', 'provider', unique=True),
    )
    
    def __repr__(self):
        return f"<UserCredential(user_id='{self.user_id}', provider='{self.provider}')>"


class UserPreference(Base):
    """User preferences and settings."""
    
    __tablename__ = 'user_preferences'
    
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    
    # UI preferences
    theme = Column(String(20), default='light')  # light, dark
    default_profile_id = Column(String(36), nullable=True)
    notification_enabled = Column(Boolean, default=True)
    
    # Extended preferences (JSON)
    preferences_json = Column(Text, nullable=True)  # Store as JSON string
    
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User", back_populates="preferences")
    
    def __repr__(self):
        return f"<UserPreference(user_id='{self.user_id}', theme='{self.theme}')>"


class OAuthAccount(Base):
    """OAuth account linking for users."""
    
    __tablename__ = 'oauth_accounts'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # OAuth provider details
    provider = Column(String(50), nullable=False)  # 'google', 'github', 'microsoft', 'discord', etc.
    provider_user_id = Column(String(255), nullable=False)  # Provider's unique ID
    
    # User info from OAuth
    provider_email = Column(String(255), nullable=True)
    provider_name = Column(String(255), nullable=True)
    provider_picture_url = Column(String(500), nullable=True)
    
    # Additional metadata
    provider_metadata = Column(JSON, nullable=True)  # Store any extra data from provider
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="oauth_accounts")
    
    # Unique constraint: one OAuth account per provider per user
    __table_args__ = (
        Index('idx_oauth_provider_user', 'user_id', 'provider', unique=True),
        Index('idx_oauth_provider_id', 'provider', 'provider_user_id', unique=True),
    )
    
    def __repr__(self):
        return f"<OAuthAccount(user_id='{self.user_id}', provider='{self.provider}')>"
    
    def to_dict(self):
        """Convert OAuth account to dictionary."""
        return {
            'id': self.id,
            'provider': self.provider,
            'provider_email': self.provider_email,
            'provider_name': self.provider_name,
            'provider_picture_url': self.provider_picture_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
        }


class AuditLog(Base):
    """Audit log for tracking user actions."""
    
    __tablename__ = 'audit_logs'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    
    # Action details
    action = Column(String(50), nullable=False, index=True)  # login, logout, configure, execute, etc.
    resource = Column(String(255), nullable=True)  # endpoint path or resource identifier
    status = Column(String(20), nullable=False)  # success, failure
    
    # Request context
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Additional details
    details = Column(Text, nullable=True)  # JSON string for extensibility
    
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    
    # Relationships
    user = relationship("User", back_populates="audit_logs")
    
    # Indexes for common queries
    __table_args__ = (
        Index('idx_audit_user_time', 'user_id', 'timestamp'),
        Index('idx_audit_action_time', 'action', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<AuditLog(action='{self.action}', user_id='{self.user_id}', status='{self.status}')>"


class PasswordResetToken(Base):
    """Temporary tokens for password reset flow."""
    
    __tablename__ = 'password_reset_tokens'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    token_hash = Column(String(255), nullable=False, index=True, unique=True)
    
    expires_at = Column(DateTime(timezone=True), nullable=False)  # 1 hour expiry
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    used = Column(Boolean, default=False, nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    
    def __repr__(self):
        return f"<PasswordResetToken(user_id='{self.user_id}', used={self.used})>"
    
    def is_valid(self):
        """Check if reset token is still valid."""
        now = datetime.now(timezone.utc)
        # Handle SQLite returning naive datetimes - assume UTC if no timezone
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return not self.used and expires_at > now


class EmailVerificationToken(Base):
    """Email verification tokens for OAuth and new user signups."""
    
    __tablename__ = 'email_verification_tokens'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Token details
    token_hash = Column(String(255), nullable=False, index=True, unique=True)
    email = Column(String(255), nullable=False, index=True)  # Email to verify (may differ from user.email during OAuth)
    
    # Token context
    verification_type = Column(String(50), nullable=False, default='oauth')  # 'oauth', 'signup', 'email_change'
    oauth_provider = Column(String(50), nullable=True)  # If OAuth-related, which provider
    
    # Token lifecycle
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    verified_at = Column(DateTime(timezone=True), nullable=True)
    
    def __repr__(self):
        return f"<EmailVerificationToken(user_id='{self.user_id}', email='{self.email}')>"
    
    def is_valid(self):
        """Check if verification token is still valid."""
        now = datetime.now(timezone.utc)
        
        # Handle timezone-naive expires_at from old tokens
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            # Make it aware by assuming UTC
            from datetime import timezone as tz
            expires_at = expires_at.replace(tzinfo=tz.utc)
        
        return self.verified_at is None and expires_at > now
    
    def is_verified(self):
        """Check if email has been verified."""
        return self.verified_at is not None


class AccessToken(Base):
    """Long-lived access tokens for REST API authentication."""
    
    __tablename__ = 'access_tokens'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Token details
    token_prefix = Column(String(10), nullable=False, index=True)  # First 8 chars for display (e.g., "tda_abcd")
    token_hash = Column(String(255), nullable=False, index=True, unique=True)  # SHA256 hash of full token
    name = Column(String(100), nullable=False)  # User-friendly name (e.g., "Production Server")
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)  # NULL = never expires
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    
    # Status
    revoked = Column(Boolean, default=False, nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    
    # Usage tracking
    use_count = Column(Integer, default=0, nullable=False)
    last_ip_address = Column(String(45), nullable=True)
    
    # Indexes
    __table_args__ = (
        Index('idx_access_token_user_active', 'user_id', 'revoked'),
    )
    
    def __repr__(self):
        return f"<AccessToken(id='{self.id}', name='{self.name}', prefix='{self.token_prefix}')>"
    
    def is_valid(self):
        """Check if access token is still valid."""
        if self.revoked:
            return False
        if self.expires_at:
            now = datetime.now(timezone.utc)
            # Handle both timezone-aware and timezone-naive datetimes
            expires_at = self.expires_at
            if expires_at.tzinfo is None:
                # If naive, assume it's UTC
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            return expires_at > now
        return True
    
    def to_dict(self, include_token=False):
        """Convert access token to dictionary for API responses."""
        # Helper to ensure timezone-aware datetime for ISO format
        def to_iso(dt):
            if dt is None:
                return None
            if dt.tzinfo is None:
                # Assume UTC if naive
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        
        data = {
            'id': self.id,
            'name': self.name,
            'token_prefix': self.token_prefix,
            'created_at': to_iso(self.created_at),
            'expires_at': to_iso(self.expires_at),
            'last_used_at': to_iso(self.last_used_at),
            'revoked': self.revoked,
            'revoked_at': to_iso(self.revoked_at),
            'use_count': self.use_count
        }
        return data


class PaneVisibility(Base):
    """Pane visibility configuration for tier-based access control."""
    
    __tablename__ = 'pane_visibility'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pane_id = Column(String(50), nullable=False, unique=True, index=True)  # conversation, executions, rag-maintenance, marketplace, credentials, admin
    pane_name = Column(String(100), nullable=False)  # Display name
    
    # Tier visibility flags
    visible_to_user = Column(Boolean, default=True, nullable=False)
    visible_to_developer = Column(Boolean, default=True, nullable=False)
    visible_to_admin = Column(Boolean, default=True, nullable=False)
    
    # Metadata
    description = Column(String(255), nullable=True)
    display_order = Column(Integer, default=0, nullable=False)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f"<PaneVisibility(pane_id='{self.pane_id}', user={self.visible_to_user}, dev={self.visible_to_developer}, admin={self.visible_to_admin})>"
    
    def to_dict(self):
        """Convert pane visibility to dictionary for API responses."""
        return {
            'id': self.id,
            'pane_id': self.pane_id,
            'pane_name': self.pane_name,
            'visible_to_user': self.visible_to_user,
            'visible_to_developer': self.visible_to_developer,
            'visible_to_admin': self.visible_to_admin,
            'description': self.description,
            'display_order': self.display_order,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class SystemSettings(Base):
    """System-wide configuration settings including rate limiting."""
    
    __tablename__ = 'system_settings'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    setting_key = Column(String(100), nullable=False, unique=True, index=True)
    setting_value = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f"<SystemSettings(key='{self.setting_key}', value='{self.setting_value}')>"
    
    def to_dict(self):
        """Convert system setting to dictionary for API responses."""
        return {
            'id': self.id,
            'key': self.setting_key,
            'value': self.setting_value,
            'description': self.description,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class CollectionSubscription(Base):
    """User subscriptions to shared marketplace RAG collections (reference-based)."""
    
    __tablename__ = 'collection_subscriptions'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    source_collection_id = Column(Integer, nullable=False, index=True)  # References collection ID in tda_config.json
    
    # Subscription configuration
    enabled = Column(Boolean, default=True, nullable=False)  # Can be toggled on/off without unsubscribing
    
    # Timestamps
    subscribed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_synced_at = Column(DateTime(timezone=True), nullable=True)  # For future sync tracking
    
    # Relationships
    user = relationship("User")
    
    # Indexes
    __table_args__ = (
        Index('idx_subscription_user_collection', 'user_id', 'source_collection_id', unique=True),
    )
    
    def __repr__(self):
        return f"<CollectionSubscription(user_id='{self.user_id}', collection_id={self.source_collection_id}, enabled={self.enabled})>"
    
    def to_dict(self):
        """Convert subscription to dictionary for API responses."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'source_collection_id': self.source_collection_id,
            'enabled': self.enabled,
            'subscribed_at': self.subscribed_at.isoformat() if self.subscribed_at else None,
            'last_synced_at': self.last_synced_at.isoformat() if self.last_synced_at else None
        }


class CollectionRating(Base):
    """User ratings and reviews for marketplace RAG collections."""
    
    __tablename__ = 'collection_ratings'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    collection_id = Column(Integer, nullable=False, index=True)  # References collection ID in tda_config.json
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Rating details
    rating = Column(Integer, nullable=False)  # 1-5 stars
    comment = Column(Text, nullable=True)  # Optional review text
    helpful_count = Column(Integer, default=0, nullable=False)  # For future "helpful" voting
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User")
    
    # Indexes
    __table_args__ = (
        Index('idx_rating_collection_user', 'collection_id', 'user_id', unique=True),
        Index('idx_rating_collection', 'collection_id'),
    )
    
    def __repr__(self):
        return f"<CollectionRating(collection_id={self.collection_id}, user_id='{self.user_id}', rating={self.rating})>"
    
    def to_dict(self, include_user_info: bool = False):
        """Convert rating to dictionary for API responses."""
        data = {
            'id': self.id,
            'collection_id': self.collection_id,
            'user_id': self.user_id,
            'rating': self.rating,
            'comment': self.comment,
            'helpful_count': self.helpful_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        if include_user_info and self.user:
            data['username'] = self.user.username
            data['user_display_name'] = self.user.display_name or self.user.username
        
        return data


class DocumentUploadConfig(Base):
    """Configuration for document upload capabilities per LLM provider."""
    
    __tablename__ = 'document_upload_config'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider = Column(String(50), nullable=False, unique=True, index=True)  # Google, Anthropic, OpenAI, Amazon, Azure, Friendli, Ollama
    
    # Configuration flags
    use_native_upload = Column(Boolean, nullable=False, default=True)  # Whether to use native upload API or fallback to text extraction
    enabled = Column(Boolean, nullable=False, default=True)  # Whether this provider supports document upload at all
    
    # Override default limits (NULL = use provider defaults from DocumentUploadConfig class)
    max_file_size_mb = Column(Integer, nullable=True)  # Override default file size limit
    supported_formats_override = Column(Text, nullable=True)  # JSON array of formats like ["pdf", "docx", "txt"]
    
    # Additional configuration
    notes = Column(Text, nullable=True)  # Admin notes about why config was changed
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f"<DocumentUploadConfig(provider='{self.provider}', enabled={self.enabled}, native={self.use_native_upload})>"
    
    def to_dict(self):
        """Convert document upload config to dictionary for API responses."""
        return {
            'id': self.id,
            'provider': self.provider,
            'use_native_upload': self.use_native_upload,
            'enabled': self.enabled,
            'max_file_size_mb': self.max_file_size_mb,
            'supported_formats_override': self.supported_formats_override,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class LLMModelCost(Base):
    """LLM model pricing information for cost tracking and analytics."""
    
    __tablename__ = 'llm_model_costs'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider = Column(String(50), nullable=False, index=True)  # Google, Anthropic, OpenAI, Amazon, Azure, Friendli, Ollama
    model = Column(String(100), nullable=False, index=True)  # Model name (e.g., gemini-2.5-flash, claude-3-5-haiku)
    
    # Pricing in USD per 1 million tokens
    input_cost_per_million = Column(Integer, nullable=False)  # Input token cost per 1M
    output_cost_per_million = Column(Integer, nullable=False)  # Output token cost per 1M
    
    # Metadata
    is_manual_entry = Column(Boolean, nullable=False, default=False)  # True if manually entered by admin
    is_fallback = Column(Boolean, nullable=False, default=False, index=True)  # True for fallback/default pricing
    source = Column(String(50), nullable=False)  # 'litellm', 'manual', 'system_default'
    last_updated = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    notes = Column(Text, nullable=True)  # Admin notes
    
    # Unique constraint: one price per provider/model combination
    __table_args__ = (
        Index('idx_llm_cost_provider_model', 'provider', 'model', unique=True),
    )
    
    def __repr__(self):
        return f"<LLMModelCost(provider='{self.provider}', model='{self.model}', in=${self.input_cost_per_million}/1M, out=${self.output_cost_per_million}/1M)>"
    
    def to_dict(self):
        """Convert model cost to dictionary for API responses."""
        return {
            'id': self.id,
            'provider': self.provider,
            'model': self.model,
            'input_cost_per_million': self.input_cost_per_million,
            'output_cost_per_million': self.output_cost_per_million,
            'is_manual_entry': self.is_manual_entry,
            'is_fallback': self.is_fallback,
            'source': self.source,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'notes': self.notes
        }


class ConsumptionProfile(Base):
    """Consumption profile model for managing user rate limits and token quotas."""
    
    __tablename__ = 'consumption_profiles'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    
    # Rate limiting parameters (per user with this profile)
    prompts_per_hour = Column(Integer, nullable=False, default=100)
    prompts_per_day = Column(Integer, nullable=False, default=1000)
    config_changes_per_hour = Column(Integer, nullable=False, default=10)
    
    # Token consumption limits (monthly)
    input_tokens_per_month = Column(Integer, nullable=True)  # NULL = unlimited
    output_tokens_per_month = Column(Integer, nullable=True)  # NULL = unlimited
    
    # Profile metadata
    is_default = Column(Boolean, default=False, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    users = relationship("User", back_populates="consumption_profile")
    
    def __repr__(self):
        return f"<ConsumptionProfile(id={self.id}, name='{self.name}')>"
    
    def to_dict(self):
        """Convert profile to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'prompts_per_hour': self.prompts_per_hour,
            'prompts_per_day': self.prompts_per_day,
            'config_changes_per_hour': self.config_changes_per_hour,
            'input_tokens_per_month': self.input_tokens_per_month,
            'output_tokens_per_month': self.output_tokens_per_month,
            'is_default': self.is_default,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'user_count': len(self.users) if self.users else 0
        }


class UserTokenUsage(Base):
    """Track token consumption per user per month for quota enforcement."""
    
    __tablename__ = 'user_token_usage'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Period tracking (YYYY-MM format for monthly tracking)
    period = Column(String(7), nullable=False, index=True)  # e.g., "2025-12"
    
    # Token consumption
    input_tokens_used = Column(Integer, nullable=False, default=0)
    output_tokens_used = Column(Integer, nullable=False, default=0)
    total_tokens_used = Column(Integer, nullable=False, default=0)
    
    # Timestamps
    first_usage_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_usage_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User", back_populates="token_usage")
    
    # Unique constraint: one record per user per period
    __table_args__ = (
        Index('idx_user_token_usage_user_period', 'user_id', 'period', unique=True),
    )
    
    def __repr__(self):
        return f"<UserTokenUsage(user_id='{self.user_id}', period='{self.period}', total={self.total_tokens_used})>"
    
    def to_dict(self):
        """Convert usage record to dictionary for API responses."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'period': self.period,
            'input_tokens_used': self.input_tokens_used,
            'output_tokens_used': self.output_tokens_used,
            'total_tokens_used': self.total_tokens_used,
            'first_usage_at': self.first_usage_at.isoformat() if self.first_usage_at else None,
            'last_usage_at': self.last_usage_at.isoformat() if self.last_usage_at else None
        }


class UserConsumption(Base):
    """Real-time consumption tracking for performance optimization and enforcement."""
    
    __tablename__ = 'user_consumption'
    
    # Primary key
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    
    # === TOKEN TRACKING ===
    # Current period (monthly)
    current_period = Column(String(7), nullable=False, index=True)  # e.g., "2025-12"
    period_started_at = Column(DateTime(timezone=True), nullable=False)
    
    # Cumulative token counts (current period)
    total_input_tokens = Column(Integer, nullable=False, default=0)
    total_output_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    
    # Profile limits (cached from consumption_profile)
    input_tokens_limit = Column(Integer, nullable=True)  # NULL = unlimited
    output_tokens_limit = Column(Integer, nullable=True)  # NULL = unlimited
    
    # === QUALITY METRICS ===
    successful_turns = Column(Integer, nullable=False, default=0)
    failed_turns = Column(Integer, nullable=False, default=0)
    total_turns = Column(Integer, nullable=False, default=0)
    # success_rate_percent computed as (successful_turns / total_turns * 100)
    
    # === RAG METRICS ===
    rag_guided_turns = Column(Integer, nullable=False, default=0)  # Turns that used RAG
    rag_output_tokens_saved = Column(Integer, nullable=False, default=0)  # Efficiency gain
    champion_cases_created = Column(Integer, nullable=False, default=0)
    collections_subscribed = Column(Text, nullable=True)  # JSON array of collection IDs
    
    # === COST TRACKING ===
    estimated_cost_usd = Column(Integer, nullable=False, default=0)  # In micro-dollars (USD × 1,000,000)
    rag_cost_saved_usd = Column(Integer, nullable=False, default=0)  # In micro-dollars (USD × 1,000,000)
    
    # === RATE LIMITING ===
    requests_this_hour = Column(Integer, nullable=False, default=0)
    requests_today = Column(Integer, nullable=False, default=0)
    hour_reset_at = Column(DateTime(timezone=True), nullable=False)
    day_reset_at = Column(DateTime(timezone=True), nullable=False)
    
    # Rate limits (cached from consumption_profile)
    prompts_per_hour_limit = Column(Integer, nullable=False, default=100)
    prompts_per_day_limit = Column(Integer, nullable=False, default=1000)
    
    # === VELOCITY TRACKING ===
    sessions_last_24h = Column(Integer, nullable=False, default=0)
    turns_last_24h = Column(Integer, nullable=False, default=0)
    peak_requests_per_hour = Column(Integer, nullable=False, default=0)
    peak_requests_per_day = Column(Integer, nullable=False, default=0)
    
    # === MODEL USAGE ===
    models_used = Column(Text, nullable=True)  # JSON object: {"gemini-2.5-flash": 150, "claude-3-5-haiku": 75}
    providers_used = Column(Text, nullable=True)  # JSON object: {"Google": 150, "Anthropic": 75}
    
    # === SESSION TRACKING ===
    total_sessions = Column(Integer, nullable=False, default=0)
    active_sessions = Column(Integer, nullable=False, default=0)  # Currently open sessions
    
    # === TIMESTAMPS ===
    first_usage_at = Column(DateTime(timezone=True), nullable=True)
    last_usage_at = Column(DateTime(timezone=True), nullable=True)
    last_updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # === RELATIONSHIPS ===
    user = relationship("User")
    
    # === INDEXES ===
    __table_args__ = (
        Index('idx_consumption_period', 'current_period'),
        Index('idx_consumption_last_usage', 'last_usage_at'),
        Index('idx_consumption_rate_limits', 'requests_this_hour', 'requests_today'),
    )
    
    def __repr__(self):
        return f"<UserConsumption(user_id='{self.user_id}', period='{self.current_period}', total_tokens={self.total_tokens})>"
    
    def to_dict(self):
        """Convert consumption to dictionary for API responses."""
        import json
        
        # Calculate computed metrics
        success_rate = (self.successful_turns / self.total_turns * 100) if self.total_turns > 0 else 0.0
        rag_activation_rate = (self.rag_guided_turns / self.total_turns * 100) if self.total_turns > 0 else 0.0
        
        # Parse JSON fields
        models_used = json.loads(self.models_used) if self.models_used else {}
        providers_used = json.loads(self.providers_used) if self.providers_used else {}
        collections_subscribed = json.loads(self.collections_subscribed) if self.collections_subscribed else []
        
        return {
            'user_id': self.user_id,
            'current_period': self.current_period,
            'period_started_at': self.period_started_at.isoformat() if self.period_started_at else None,
            
            # Token metrics
            'total_input_tokens': self.total_input_tokens,
            'total_output_tokens': self.total_output_tokens,
            'total_tokens': self.total_tokens,
            'input_tokens_limit': self.input_tokens_limit,
            'output_tokens_limit': self.output_tokens_limit,
            'input_tokens_remaining': (self.input_tokens_limit - self.total_input_tokens) if self.input_tokens_limit else None,
            'output_tokens_remaining': (self.output_tokens_limit - self.total_output_tokens) if self.output_tokens_limit else None,
            
            # Quality metrics
            'successful_turns': self.successful_turns,
            'failed_turns': self.failed_turns,
            'total_turns': self.total_turns,
            'success_rate_percent': round(success_rate, 2),
            
            # RAG metrics
            'rag_guided_turns': self.rag_guided_turns,
            'rag_activation_rate_percent': round(rag_activation_rate, 2),
            'rag_output_tokens_saved': self.rag_output_tokens_saved,
            'champion_cases_created': self.champion_cases_created,
            'collections_subscribed': collections_subscribed,
            
            # Cost metrics
            'estimated_cost_usd': self.estimated_cost_usd / 1000000.0,  # Convert micro-dollars to dollars
            'rag_cost_saved_usd': self.rag_cost_saved_usd / 1000000.0,
            
            # Rate limiting
            'requests_this_hour': self.requests_this_hour,
            'requests_today': self.requests_today,
            'hour_reset_at': self.hour_reset_at.isoformat() if self.hour_reset_at else None,
            'day_reset_at': self.day_reset_at.isoformat() if self.day_reset_at else None,
            'prompts_per_hour_limit': self.prompts_per_hour_limit,
            'prompts_per_day_limit': self.prompts_per_day_limit,
            'requests_hour_remaining': self.prompts_per_hour_limit - self.requests_this_hour,
            'requests_day_remaining': self.prompts_per_day_limit - self.requests_today,
            
            # Velocity
            'sessions_last_24h': self.sessions_last_24h,
            'turns_last_24h': self.turns_last_24h,
            'peak_requests_per_hour': self.peak_requests_per_hour,
            'peak_requests_per_day': self.peak_requests_per_day,
            
            # Model usage
            'models_used': models_used,
            'providers_used': providers_used,
            
            # Session tracking
            'total_sessions': self.total_sessions,
            'active_sessions': self.active_sessions,
            
            # Timestamps
            'first_usage_at': self.first_usage_at.isoformat() if self.first_usage_at else None,
            'last_usage_at': self.last_usage_at.isoformat() if self.last_usage_at else None,
            'last_updated_at': self.last_updated_at.isoformat() if self.last_updated_at else None
        }


class ConsumptionTurn(Base):
    """Granular turn-level tracking for audit trail and analytics."""
    
    __tablename__ = 'consumption_turns'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    session_id = Column(String(36), nullable=False, index=True)
    turn_number = Column(Integer, nullable=False)
    
    # Query and session context
    user_query = Column(Text, nullable=True)  # The user's question/prompt
    session_name = Column(String(255), nullable=True)  # Session display name
    
    # Token usage
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    total_tokens = Column(Integer, nullable=False)
    
    # Model info
    provider = Column(String(50), nullable=False)
    model = Column(String(100), nullable=False)
    
    # Cost
    cost_usd_cents = Column(Integer, nullable=False, default=0)  # In micro-dollars (USD × 1,000,000)
    
    # Quality
    status = Column(String(20), nullable=False)  # success, failure, partial
    
    # RAG
    rag_used = Column(Boolean, nullable=False, default=False)
    rag_tokens_saved = Column(Integer, nullable=False, default=0)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    
    # Relationships
    user = relationship("User")
    
    # Indexes
    __table_args__ = (
        Index('idx_turn_user_session', 'user_id', 'session_id'),
        Index('idx_turn_created', 'created_at'),
    )
    
    def __repr__(self):
        return f"<ConsumptionTurn(user_id='{self.user_id}', session='{self.session_id}', turn={self.turn_number})>"
    
    def to_dict(self):
        """Convert turn to dictionary for API responses."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'session_id': self.session_id,
            'turn_number': self.turn_number,
            'user_query': self.user_query,
            'session_name': self.session_name,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'total_tokens': self.total_tokens,
            'provider': self.provider,
            'model': self.model,
            'cost_usd': self.cost_usd_cents / 1000000.0,
            'status': self.status,
            'rag_used': self.rag_used,
            'rag_tokens_saved': self.rag_tokens_saved,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ConsumptionPeriodsArchive(Base):
    """Historical snapshots for period rollover and analytics."""
    
    __tablename__ = 'consumption_periods_archive'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    period = Column(String(7), nullable=False, index=True)  # e.g., "2025-12"
    
    # Snapshot of metrics at period end
    total_input_tokens = Column(Integer, nullable=False)
    total_output_tokens = Column(Integer, nullable=False)
    total_tokens = Column(Integer, nullable=False)
    successful_turns = Column(Integer, nullable=False)
    failed_turns = Column(Integer, nullable=False)
    total_turns = Column(Integer, nullable=False)
    rag_guided_turns = Column(Integer, nullable=False)
    rag_output_tokens_saved = Column(Integer, nullable=False)
    champion_cases_created = Column(Integer, nullable=False)
    estimated_cost_usd = Column(Integer, nullable=False)  # In micro-dollars (USD × 1,000,000)
    rag_cost_saved_usd = Column(Integer, nullable=False)  # In micro-dollars (USD × 1,000,000)
    total_sessions = Column(Integer, nullable=False)
    
    # Period boundaries
    period_started_at = Column(DateTime(timezone=True), nullable=False)
    period_ended_at = Column(DateTime(timezone=True), nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User")
    
    # Indexes
    __table_args__ = (
        Index('idx_archive_user_period', 'user_id', 'period', unique=True),
        Index('idx_archive_period', 'period'),
    )
    
    def __repr__(self):
        return f"<ConsumptionPeriodsArchive(user_id='{self.user_id}', period='{self.period}')>"
    
    def to_dict(self):
        """Convert archive to dictionary for API responses."""
        success_rate = (self.successful_turns / self.total_turns * 100) if self.total_turns > 0 else 0.0
        rag_activation_rate = (self.rag_guided_turns / self.total_turns * 100) if self.total_turns > 0 else 0.0
        
        return {
            'id': self.id,
            'user_id': self.user_id,
            'period': self.period,
            'total_input_tokens': self.total_input_tokens,
            'total_output_tokens': self.total_output_tokens,
            'total_tokens': self.total_tokens,
            'successful_turns': self.successful_turns,
            'failed_turns': self.failed_turns,
            'total_turns': self.total_turns,
            'success_rate_percent': round(success_rate, 2),
            'rag_guided_turns': self.rag_guided_turns,
            'rag_activation_rate_percent': round(rag_activation_rate, 2),
            'rag_output_tokens_saved': self.rag_output_tokens_saved,
            'champion_cases_created': self.champion_cases_created,
            'estimated_cost_usd': self.estimated_cost_usd / 1000000.0,
            'rag_cost_saved_usd': self.rag_cost_saved_usd / 1000000.0,
            'total_sessions': self.total_sessions,
            'period_started_at': self.period_started_at.isoformat() if self.period_started_at else None,
            'period_ended_at': self.period_ended_at.isoformat() if self.period_ended_at else None,
            'archived_at': self.archived_at.isoformat() if self.archived_at else None
        }


class RecommendedModel(Base):
    """Recommended models for each LLM provider.

    These are the models that appear as "Recommended" in the model selection UI.
    Models can be recommended globally or for specific use cases.
    """

    __tablename__ = 'recommended_models'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider = Column(String(50), nullable=False, index=True)  # Google, Anthropic, OpenAI, Amazon, Azure, Friendli, Ollama
    model_pattern = Column(String(200), nullable=False)  # Model name or pattern with wildcards (e.g., "*gpt-4o-mini", "gemini-2.5-flash")

    # Metadata
    notes = Column(Text, nullable=True)  # Description of why this model is recommended
    is_active = Column(Boolean, nullable=False, default=True)  # Can be disabled without deletion
    source = Column(String(50), nullable=False, default='config_default')  # 'config_default', 'manual'

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Unique constraint: one entry per provider/pattern combination
    __table_args__ = (
        Index('idx_recommended_provider_pattern', 'provider', 'model_pattern', unique=True),
    )

    def __repr__(self):
        return f"<RecommendedModel(provider='{self.provider}', pattern='{self.model_pattern}', active={self.is_active})>"

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'provider': self.provider,
            'model_pattern': self.model_pattern,
            'notes': self.notes,
            'is_active': self.is_active,
            'source': self.source,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ProviderAvailableModel(Base):
    """
    Available models for LLM providers that don't have dynamic model listing APIs.

    Initially designed for Friendli serverless models, but extensible to other providers.
    Models can have different billing types (token-based, time-based, free) and statuses.

    This table controls which models appear in the UI dropdown. It is separate from
    llm_model_costs which handles pricing - a model can be deprecated (hidden from dropdown)
    while still having cost data for historical tracking.
    """

    __tablename__ = 'provider_available_models'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider = Column(String(50), nullable=False, index=True)  # e.g., "Friendli"
    model_id = Column(String(200), nullable=False, index=True)  # e.g., "meta-llama/Llama-3.3-70B-Instruct"
    display_name = Column(String(200), nullable=True)  # Human-readable name for UI

    # Billing and availability
    billing_type = Column(String(20), nullable=False, default='token')  # 'token', 'time', 'free'
    status = Column(String(20), nullable=False, default='active')  # 'active', 'deprecated', 'coming_soon'
    endpoint_type = Column(String(20), nullable=False, default='serverless')  # 'serverless', 'dedicated', 'both'

    # Metadata
    notes = Column(Text, nullable=True)  # Additional info about the model
    source = Column(String(50), nullable=False, default='config_default')  # 'config_default', 'manual', 'api_sync'
    is_active = Column(Boolean, nullable=False, default=True)  # Soft delete support

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
                       onupdate=lambda: datetime.now(timezone.utc))

    # Unique constraint: one entry per provider/model/endpoint_type combination
    __table_args__ = (
        Index('idx_provider_model_endpoint', 'provider', 'model_id', 'endpoint_type', unique=True),
        Index('idx_provider_status', 'provider', 'status'),
    )

    def __repr__(self):
        return f"<ProviderAvailableModel(provider='{self.provider}', model='{self.model_id}', status='{self.status}')>"

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'provider': self.provider,
            'model_id': self.model_id,
            'display_name': self.display_name,
            'billing_type': self.billing_type,
            'status': self.status,
            'endpoint_type': self.endpoint_type,
            'notes': self.notes,
            'source': self.source,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }