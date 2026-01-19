"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2024-01-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tenants table
    op.create_table(
        'tenants',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('description', sa.String(1000), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_tenants_name', 'tenants', ['name'])

    # Cache policies table
    op.create_table(
        'cache_policies',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('description', sa.String(1000), nullable=True),
        sa.Column('ttl_seconds', sa.Integer(), default=300),
        sa.Column('stale_seconds', sa.Integer(), default=60),
        sa.Column('vary_headers_json', postgresql.JSONB(), default=list),
        sa.Column('cacheable_statuses_json', postgresql.JSONB(), default=list),
        sa.Column('max_body_bytes', sa.Integer(), default=10485760),
        sa.Column('cache_private', sa.Boolean(), default=False),
        sa.Column('cache_no_store', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # API keys table
    op.create_table(
        'api_keys',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('key', sa.String(64), nullable=False, unique=True),
        sa.Column('key_prefix', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), default='active'),
        sa.Column('quota_daily', sa.Integer(), default=0),
        sa.Column('quota_monthly', sa.Integer(), default=0),
        sa.Column('rate_limit_rps', sa.Float(), nullable=True),
        sa.Column('rate_limit_burst', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_api_keys_key', 'api_keys', ['key'])
    op.create_index('ix_api_keys_key_prefix', 'api_keys', ['key_prefix'])
    op.create_index('ix_api_keys_tenant_id', 'api_keys', ['tenant_id'])

    # Routes table
    op.create_table(
        'routes',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.String(1000), nullable=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=True),
        sa.Column('path_pattern', sa.String(500), nullable=False),
        sa.Column('methods', postgresql.JSONB(), default=list),
        sa.Column('upstream_base_url', sa.String(1000), nullable=False),
        sa.Column('upstream_path_rewrite', sa.String(500), nullable=True),
        sa.Column('timeout_ms', sa.Integer(), default=30000),
        sa.Column('request_headers_add', postgresql.JSONB(), default=dict),
        sa.Column('request_headers_remove', postgresql.JSONB(), default=list),
        sa.Column('response_headers_add', postgresql.JSONB(), default=dict),
        sa.Column('policy_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('cache_policies.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rate_limit_rps', sa.Float(), nullable=True),
        sa.Column('rate_limit_burst', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('priority', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_routes_name', 'routes', ['name'])
    op.create_index('ix_routes_tenant_id', 'routes', ['tenant_id'])
    op.create_index('ix_routes_policy_id', 'routes', ['policy_id'])
    op.create_index('ix_routes_path_pattern', 'routes', ['path_pattern'])

    # Request logs table
    op.create_table(
        'request_logs',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('request_id', sa.String(64), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('tenants.id', ondelete='SET NULL'), nullable=True),
        sa.Column('api_key_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('api_keys.id', ondelete='SET NULL'), nullable=True),
        sa.Column('route_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('routes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('path', sa.String(2000), nullable=False),
        sa.Column('query_string', sa.String(2000), nullable=True),
        sa.Column('client_ip', sa.String(50), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=False),
        sa.Column('response_size_bytes', sa.Integer(), nullable=True),
        sa.Column('cache_status', sa.String(20), default='miss'),
        sa.Column('error_type', sa.String(30), default='none'),
        sa.Column('error_message', sa.String(1000), nullable=True),
        sa.Column('upstream_latency_ms', sa.Integer(), nullable=True),
        sa.Column('upstream_status_code', sa.Integer(), nullable=True),
    )
    op.create_index('ix_request_logs_request_id', 'request_logs', ['request_id'])
    op.create_index('ix_request_logs_timestamp', 'request_logs', ['timestamp'])
    op.create_index('ix_request_logs_tenant_id', 'request_logs', ['tenant_id'])
    op.create_index('ix_request_logs_api_key_id', 'request_logs', ['api_key_id'])
    op.create_index('ix_request_logs_route_id', 'request_logs', ['route_id'])

    # Block rules table
    op.create_table(
        'block_rules',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('api_key_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('api_keys.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reason', sa.String(30), nullable=False),
        sa.Column('reason_detail', sa.String(1000), nullable=True),
        sa.Column('anomaly_score', sa.Float(), nullable=True),
        sa.Column('rate_at_block', sa.Float(), nullable=True),
        sa.Column('error_rate_at_block', sa.Float(), nullable=True),
        sa.Column('blocked_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('blocked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('unblocked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('unblocked_by', sa.String(255), nullable=True),
        sa.Column('unblock_reason', sa.String(500), nullable=True),
    )
    op.create_index('ix_block_rules_api_key_id', 'block_rules', ['api_key_id'])


def downgrade() -> None:
    op.drop_table('block_rules')
    op.drop_table('request_logs')
    op.drop_table('routes')
    op.drop_table('api_keys')
    op.drop_table('cache_policies')
    op.drop_table('tenants')
