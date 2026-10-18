from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import String, Boolean, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.pattern_group import PatternGroup


class TransactionPattern(Base):
    __tablename__ = "transaction_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    to_account_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True)
    group_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("groups.id"), nullable=True)
    pattern_group_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("pattern_groups.id", ondelete="SET NULL"), nullable=True
    )
    typical_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_income: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    memo_template: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    payment_day_of_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payment_month_of_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    category: Mapped["Category"] = relationship("Category")
    account: Mapped["Account"] = relationship("Account", foreign_keys=[account_id])
    to_account: Mapped[Optional["Account"]] = relationship("Account", foreign_keys=[to_account_id])
    group: Mapped[Optional["Group"]] = relationship("Group")
    pattern_group: Mapped[Optional["PatternGroup"]] = relationship("PatternGroup", back_populates="patterns")
