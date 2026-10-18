from datetime import date, datetime
from typing import List, Optional
from sqlalchemy import String, Boolean, Integer, DateTime, Date, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    initial_balance: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    adjustment_amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    classification: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # リレーション
    transactions: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="account"
    )
