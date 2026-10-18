"""過去1年の取引実績からmonthlyパターンの支払日初期値を設定する

過去1年のトランザクションを集計し、最頻出日（最頻値シェア≥50%、標準偏差≤5）を
payment_day_of_month の初期値として設定する。

設定対象（17件）:
  id=39  月次_AWS                 → 1日  (99%, stddev=0.1)
  id=9   月次_資金移動JCBへ       → 10日 (83%, stddev=0.9)
  id=11  月次_資金移動IYカード    → 10日 (69%, stddev=3.9)
  id=34  月次_給料_花子           → 20日 (100%, stddev=0.0)
  id=17,18,19,20,21,22,23,24,
     25,26,27,30,31               → 22日 (給与・控除系、stddev=0.8〜4.7)

スキップ（12件）:
  携帯系(36,37,42,43,45): 2クラスタに分散（8-13日 / 28-31日）
  月次_CLAUDE(44): データ4件のみ
  月次_塾や稽古(5,33): 8種類の日付に分散
  月次_KindleUnlimited(32): 16種類の日付に分散
  日次_Amazon(38), 日次_ヨークフーズ(40): 日次購買
  その他_楽天(29): 8種類の日付に分散

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 分析結果に基づく (pattern_id, payment_day_of_month) マッピング
_PAYMENT_DAYS: list[tuple[int, int]] = [
    (39, 1),   # 月次_AWS
    (9,  10),  # 月次_【資金移動】JCBカードへ
    (11, 10),  # 月次_資金移動_IYカード支払い
    (34, 20),  # 月次_給料_花子
    (17, 22),  # 月次_給料や賃金
    (18, 22),  # 月次_その他の手当
    (19, 22),  # 月次_残業手当
    (20, 22),  # 月次_その他の手当
    (21, 22),  # 月次_所得税
    (22, 22),  # 月次_住民税
    (23, 22),  # 月次_年金保険料
    (24, 22),  # 月次_介護保険料
    (25, 22),  # 月次_雇用保険料
    (26, 22),  # 月次_組合費
    (27, 22),  # 月次_組合費
    (30, 22),  # 月次_給料口座振り込み1
    (31, 22),  # 月次_給料口座振り込み2
]


def upgrade() -> None:
    conn = op.get_bind()
    for pattern_id, day in _PAYMENT_DAYS:
        conn.execute(
            sa.text(
                "UPDATE transaction_patterns"
                " SET payment_day_of_month = :day"
                " WHERE id = :pid AND payment_day_of_month IS NULL"
            ),
            {"day": day, "pid": pattern_id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    ids = [pid for pid, _ in _PAYMENT_DAYS]
    conn.execute(
        sa.text(
            "UPDATE transaction_patterns"
            " SET payment_day_of_month = NULL"
            " WHERE id = ANY(:ids)"
        ),
        {"ids": ids},
    )
