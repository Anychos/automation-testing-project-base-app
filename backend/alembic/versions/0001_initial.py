"""Initial BookingLab schema."""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(5), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("uq_users_lower_email", "users", [sa.text("lower(email)")], unique=True)
    op.create_table("rooms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("price_per_30min_kopeks", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False))
    op.create_index("uq_rooms_lower_name", "rooms", [sa.text("lower(name)")], unique=True)
    op.create_table("bookings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("room_id", sa.Uuid(), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("title", sa.String(60), nullable=False),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("attendees", sa.Integer(), nullable=False),
        sa.Column("total_price_kopeks", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_request_id", sa.Uuid(), nullable=True))
    op.create_index("ix_bookings_room_day", "bookings", ["room_id", "booking_date"])
    op.create_table("outbox_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("booking_id", sa.Uuid(), sa.ForeignKey("bookings.id"), nullable=False),
        sa.Column("payload", sa.String(2000), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("processed_payment_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False))

def downgrade():
    op.drop_table("processed_payment_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_bookings_room_day", table_name="bookings")
    op.drop_table("bookings")
    op.drop_index("uq_rooms_lower_name", table_name="rooms")
    op.drop_table("rooms")
    op.drop_index("uq_users_lower_email", table_name="users")
    op.drop_table("users")
