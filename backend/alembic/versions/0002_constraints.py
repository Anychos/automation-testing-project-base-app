"""Protect core enum and numeric invariants in the database."""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade():
    op.create_check_constraint("ck_users_role", "users", "role IN ('USER', 'ADMIN')")
    op.create_check_constraint("ck_rooms_capacity", "rooms", "capacity BETWEEN 2 AND 10")
    op.create_check_constraint("ck_rooms_price", "rooms", "price_per_30min_kopeks BETWEEN 10000 AND 200000")
    op.create_check_constraint("ck_bookings_status", "bookings", "status IN ('CREATED','PAYMENT_PENDING','CONFIRMED','PAYMENT_FAILED','CANCELLED','EXPIRED')")
    op.create_check_constraint("ck_bookings_duration", "bookings", "duration_minutes IN (30,60,90,120)")
    op.create_check_constraint("ck_bookings_attendees", "bookings", "attendees >= 1")
    op.create_check_constraint("ck_bookings_price", "bookings", "total_price_kopeks > 0")

def downgrade():
    for table, name in (("bookings", "ck_bookings_price"), ("bookings", "ck_bookings_attendees"),
                        ("bookings", "ck_bookings_duration"), ("bookings", "ck_bookings_status"),
                        ("rooms", "ck_rooms_price"), ("rooms", "ck_rooms_capacity"), ("users", "ck_users_role")):
        op.drop_constraint(name, table, type_="check")
