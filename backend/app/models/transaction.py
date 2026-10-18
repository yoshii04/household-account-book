from datetime import datetime, date
from typing import Optional
from sqlalchemy import String, Boolean, Integer, Date, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False
    )
    income_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expense_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    memo: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    group_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("groups.id"), nullable=True
    )
    is_transfer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    transfer_detail: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    pattern_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("transaction_patterns.id", ondelete="SET NULL"), nullable=True
    )
    import_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # リレーション
    category: Mapped["Category"] = relationship("Category", back_populates="transactions")
    account: Mapped["Account"] = relationship("Account", back_populates="transactions")
    group: Mapped[Optional["Group"]] = relationship("Group", back_populates="transactions")
    pattern: Mapped[Optional["TransactionPattern"]] = relationship("TransactionPattern")


class ImportLog(Base):
    __tablename__ = "import_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
