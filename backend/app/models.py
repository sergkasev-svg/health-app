"""SQLAlchemy models для SaaS."""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, TIMESTAMP, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


# --- Memory + Dynamics: история анализов, маркеры, напоминания ---
class ReportHistory(Base):
    __tablename__ = "report_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    report_type = Column(String(64), nullable=False)
    source_name = Column(String(255), nullable=True)
    raw_payload = Column(JSON, nullable=True)
    ai_result = Column(JSON, nullable=True)
    summary_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MarkerSnapshot(Base):
    __tablename__ = "marker_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("report_history.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, index=True, nullable=False)
    marker_key = Column(String(128), index=True, nullable=False)
    marker_value = Column(String(128), nullable=True)
    marker_numeric = Column(String(64), nullable=True)
    marker_unit = Column(String(32), nullable=True)
    marker_status = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FollowUpReminder(Base):
    __tablename__ = "followup_reminders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    report_id = Column(Integer, ForeignKey("report_history.id", ondelete="SET NULL"), nullable=True)
    reminder_type = Column(String(64), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    is_done = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    # Строковый id из auth_store (u_..., pk_...) — для memory/dynamics при сессионном логине
    auth_subject = Column(String(128), unique=True, index=True, nullable=True)
    email = Column(Text, unique=True, index=True, nullable=True)
    password = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    reports = relationship("Report", back_populates="user", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    data = Column(JSON, nullable=True)  # входные данные (lab_markers, symptoms, profile)
    result = Column(JSON, nullable=True)  # результат (text, hypotheses, plan)
    created_at = Column(TIMESTAMP, server_default=func.now(), index=True)

    user = relationship("User", back_populates="reports")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(Text, default="free", index=True)  # free, premium, subscription, cancelled
    plan = Column(Text, default="free")  # free, premium, monthly, yearly
    stripe_subscription_id = Column(Text, nullable=True)
    stripe_customer_id = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    expires_at = Column(TIMESTAMP, nullable=True)

    user = relationship("User", back_populates="subscriptions")
