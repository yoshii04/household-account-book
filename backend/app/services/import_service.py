"""
Actual.TXT インポートサービス

ファイル仕様:
- エンコーディング: UTF-16LE + BOM
- セパレータ: タブ区切り (TSV)
- ヘッダー: 日　付 / カテゴリー / アカウント / 入金額 / 出金額 / メ　モ / グループ
"""
import csv
import hashlib
import io
import re
from datetime import datetime
from typing import Optional


from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.account import Account
from app.models.group import Group
from app.models.transaction import Transaction, ImportLog
from app.schemas.import_result import ImportResult


# アカウントコードからタイプを推定
_CASH_PREFIXES = ("10_", "11_", "12_", "13_")
_BANK_PREFIXES = ("30_", "34_", "54_", "59_", "5D_")
_EMONEY_PREFIXES = ("26_", "28_", "2b_", "2B_")
_CARD_PREFIXES = ("40_", "41_", "42_", "43_", "44_", "45_", "46_", "47_", "48_",
                  "49_", "4a_", "4A_", "4b_", "4B_", "4c_", "4C_", "4d_", "4D_",
                  "4e_", "4E_", "4f_", "4F_", "4g_", "4G_", "4h_", "4H_",
                  "4i_", "4I_", "4j_", "4J_", "4k_", "4K_", "4l_", "4L_",
                  "4m_", "4M_", "4n_", "4N_")


def _guess_account_type(code: str) -> str:
    if any(code.startswith(p) for p in _CASH_PREFIXES):
        return "cash"
    if any(code.startswith(p) for p in _BANK_PREFIXES):
        return "bank"
    if any(code.startswith(p) for p in _EMONEY_PREFIXES):
        return "e-money"
    if any(code.startswith(p) for p in _CARD_PREFIXES):
        return "card"
    return "other"


def _make_hash(date_str: str, category_path: str, account_code: str,
               income: str, expense: str, memo: str) -> str:
    raw = f"{date_str}|{category_path}|{account_code}|{income}|{expense}|{memo}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_RE_TRANSFER_TO = re.compile(r'^【資金移動】- (.+)へ -$')
_RE_TRANSFER_FROM = re.compile(r'^【資金移動】- (.+)から -$')


def _make_transfer_counterpart(
    date_str: str,
    category_path: str,
    account_code: str,
    income_str: str,
    expense_str: str,
    income: int,
    expense: int,
    memo: str,
    group_code: str,
) -> Optional[dict]:
    """
    資金移動の対向トランザクションデータを生成する。
    '【資金移動】- X へ -'（送金側）→ 受取側: account=X, income=expense
    '【資金移動】- X から -'（受取側）→ 送金側: account=X, expense=income
    対向が不要なパターン（カード引落し・ローン返済等）は None を返す。
    """
    m_to = _RE_TRANSFER_TO.match(category_path)
    m_from = _RE_TRANSFER_FROM.match(category_path)

    if m_to:
        dest_account = m_to.group(1)
        cp_category = f"【資金移動】- {account_code}から -"
        cp_account = dest_account
        cp_income_str = expense_str
        cp_expense_str = ""
        cp_income = expense
        cp_expense = 0
    elif m_from:
        src_account = m_from.group(1)
        cp_category = f"【資金移動】- {account_code}へ -"
        cp_account = src_account
        cp_income_str = ""
        cp_expense_str = income_str
        cp_income = 0
        cp_expense = income
    else:
        return None

    cp_hash = _make_hash(date_str, cp_category, cp_account, cp_income_str, cp_expense_str, memo)

    return {
        "date_str": date_str,
        "category_path": cp_category,
        "account_code": cp_account,
        "income_str": cp_income_str,
        "expense_str": cp_expense_str,
        "income": cp_income,
        "expense": cp_expense,
        "memo": memo,
        "group_code": group_code,
        "hash": cp_hash,
    }


def _upsert_category(db: Session, full_path: str) -> tuple[Category, bool]:
    """カテゴリを upsert。(category, is_new) を返す。"""
    existing = db.query(Category).filter(Category.full_path == full_path).first()
    if existing:
        return existing, False

    is_transfer = full_path.startswith("【資金移動】") or full_path.startswith("【ﾛｰﾝ】")

    parts = full_path.split("/", 1)
    parent_code = parts[0]

    if len(parts) == 1:
        # 親カテゴリ自体を登録
        cat = Category(
            code=parent_code,
            name=_extract_display_name(parent_code),
            full_path=full_path,
            is_transfer=is_transfer,
        )
        db.add(cat)
        db.flush()
        return cat, True
    else:
        child_name = parts[1]
        # 親を先に upsert
        parent, _ = _upsert_category(db, parent_code)
        cat = Category(
            code=child_name,
            name=child_name,
            parent_id=parent.id,
            full_path=full_path,
            is_transfer=is_transfer,
        )
        db.add(cat)
        db.flush()
        return cat, True


def _extract_display_name(code: str) -> str:
    """コードをそのまま表示名として使用する。例: 'A30_通信費' → 'A30_通信費'"""
    return code


def _upsert_account(db: Session, code: str) -> tuple[Account, bool]:
    existing = db.query(Account).filter(Account.code == code).first()
    if existing:
        return existing, False
    acc = Account(
        code=code,
        name=re.sub(r"^\d+[A-Za-z]*_", "", code),  # コードから番号プレフィックスを除去
        account_type=_guess_account_type(code),
    )
    db.add(acc)
    db.flush()
    return acc, True


def _upsert_group(db: Session, code: str) -> tuple[Group, bool]:
    existing = db.query(Group).filter(Group.code == code).first()
    if existing:
        return existing, False
    grp = Group(
        code=code,
        name=re.sub(r"^\d+_", "", code),  # '20_太郎' → '太郎'
    )
    db.add(grp)
    db.flush()
    return grp, True


def _parse_amount(value: str) -> int:
    """金額文字列を整数に変換。空文字・変換不能は 0。"""
    value = value.strip().replace(",", "")
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


async def import_actual_txt(
    db: Session,
    content: bytes,
    filename: str,
    mode: str = "append",
    skip_loan: bool = False,
) -> ImportResult:
    """
    Actual.TXT (UTF-16LE BOM 付き TSV) を解析して DB に格納する。

    mode:
      - "replace": 既存トランザクションを全削除してからインポート
      - "append":  既存データを保持したまま追加インポート
    skip_loan:
      - True: 【ﾛｰﾝ】カテゴリ行をスキップ（ローン返済スケジュール機能で登録済みの場合）
    """
    deleted_rows = 0
    if mode == "replace":
        deleted_rows = db.query(Transaction).delete()
        db.flush()

    # UTF-16 デコード（BOM を自動認識）
    try:
        text = content.decode("utf-16")
    except UnicodeDecodeError:
        # フォールバック: UTF-8 試行
        text = content.decode("utf-8", errors="replace")

    lines = text.splitlines()
    if not lines:
        return ImportResult(
            status="error",
            filename=filename,
            total_rows=0,
            imported_rows=0,
            skipped_rows=0,
            error_rows=0,
            error_detail="ファイルが空です",
        )

    # ヘッダー行の BOM 文字を除去
    lines[0] = lines[0].lstrip("\ufeff").lstrip("\u200b")

    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter="\t")

    total = 0
    imported = 0
    skipped = 0
    skipped_loan = 0
    errors = 0
    new_categories: list[str] = []
    new_accounts: list[str] = []
    new_groups: list[str] = []
    error_messages: list[str] = []
    skipped_details: list[dict] = []  # スキップ行の詳細（理由付き）

    # 資金移動の対向トランザクション自動生成用
    all_hashes_this_import: set[str] = set()
    pending_counterparts: dict[str, dict] = {}  # hash → 対向データ

    # フィールド名の正規化マッピング（全角スペース対応）
    FIELD_DATE = None
    FIELD_CATEGORY = None
    FIELD_ACCOUNT = None
    FIELD_INCOME = None
    FIELD_EXPENSE = None
    FIELD_MEMO = None
    FIELD_GROUP = None

    fieldnames = reader.fieldnames or []
    for f in fieldnames:
        stripped = f.strip().replace("\u3000", "").replace(" ", "")
        if stripped in ("日付", "日　付"):
            FIELD_DATE = f
        elif stripped == "カテゴリー":
            FIELD_CATEGORY = f
        elif stripped == "アカウント":
            FIELD_ACCOUNT = f
        elif stripped == "入金額":
            FIELD_INCOME = f
        elif stripped == "出金額":
            FIELD_EXPENSE = f
        elif stripped in ("メモ", "メ　モ"):
            FIELD_MEMO = f
        elif stripped == "グループ":
            FIELD_GROUP = f

    # ヘッダーが見つからない場合は位置で推定
    if not FIELD_DATE and fieldnames:
        FIELD_DATE = fieldnames[0]
        FIELD_CATEGORY = fieldnames[1] if len(fieldnames) > 1 else None
        FIELD_ACCOUNT = fieldnames[2] if len(fieldnames) > 2 else None
        FIELD_INCOME = fieldnames[3] if len(fieldnames) > 3 else None
        FIELD_EXPENSE = fieldnames[4] if len(fieldnames) > 4 else None
        FIELD_MEMO = fieldnames[5] if len(fieldnames) > 5 else None
        FIELD_GROUP = fieldnames[6] if len(fieldnames) > 6 else None

    for row in reader:
        total += 1
        try:
            # row.get() は列数不足の行でヘッダーキーに None を返すため or "" で安全化
            date_str = (row.get(FIELD_DATE) or "").strip() if FIELD_DATE else ""
            category_path = (row.get(FIELD_CATEGORY) or "").strip() if FIELD_CATEGORY else ""
            account_code = (row.get(FIELD_ACCOUNT) or "").strip() if FIELD_ACCOUNT else ""
            income_str = (row.get(FIELD_INCOME) or "").strip() if FIELD_INCOME else ""
            expense_str = (row.get(FIELD_EXPENSE) or "").strip() if FIELD_EXPENSE else ""
            memo = (row.get(FIELD_MEMO) or "").strip() if FIELD_MEMO else ""
            group_code = (row.get(FIELD_GROUP) or "").strip() if FIELD_GROUP else ""

            # 必須項目チェック
            if not date_str or not category_path or not account_code:
                missing = []
                if not date_str:
                    missing.append("日付")
                if not category_path:
                    missing.append("カテゴリ")
                if not account_code:
                    missing.append("アカウント")
                reason = f"必須項目不足: {', '.join(missing)}"
                errors += 1
                skipped += 1
                error_messages.append(f"行{total}: {reason}")
                skipped_details.append({
                    "line": total, "date": date_str,
                    "category": category_path, "account": account_code,
                    "reason": reason,
                })
                continue

            # 【ﾛｰﾝ】行スキップ（オプション）
            if skip_loan and category_path.startswith("【ﾛｰﾝ】"):
                skipped += 1
                skipped_loan += 1
                skipped_details.append({
                    "line": total, "date": date_str,
                    "category": category_path, "account": account_code,
                    "reason": "ローンデータのためスキップ",
                })
                continue

            # 日付パース
            try:
                tx_date = datetime.strptime(date_str, "%Y/%m/%d").date()
            except ValueError:
                reason = f"日付フォーマットエラー: '{date_str}' (YYYY/MM/DD 形式で入力してください)"
                errors += 1
                skipped += 1
                error_messages.append(f"行{total}: {reason}")
                skipped_details.append({
                    "line": total, "date": date_str,
                    "category": category_path, "account": account_code,
                    "reason": reason,
                })
                continue

            # 金額
            income = _parse_amount(income_str)
            expense = _parse_amount(expense_str)

            # ハッシュ（対向生成・追跡用）
            import_hash = _make_hash(date_str, category_path, account_code,
                                     income_str, expense_str, memo)

            # 資金移動フラグ（【資金移動】と【ﾛｰﾝ】はどちらも集計対象外）
            is_transfer = (
                category_path.startswith("【資金移動】")
                or category_path.startswith("【ﾛｰﾝ】")
            )

            # 資金移動の対向データを収集
            if category_path.startswith("【資金移動】"):
                cp = _make_transfer_counterpart(
                    date_str, category_path, account_code,
                    income_str, expense_str, income, expense, memo, group_code,
                )
                if cp and cp["hash"] not in pending_counterparts:
                    pending_counterparts[cp["hash"]] = cp

            # 【ﾛｰﾝ】行はローン口座の受取側。対応する【資金移動】の対向自動生成を抑制する
            if category_path.startswith("【ﾛｰﾝ】"):
                for cp_hash, cp in pending_counterparts.items():
                    if cp["account_code"] == account_code and cp["date_str"] == date_str:
                        all_hashes_this_import.add(cp_hash)
                        break

            # カテゴリ upsert
            category, cat_is_new = _upsert_category(db, category_path)
            if cat_is_new:
                new_categories.append(category_path)

            # アカウント upsert
            account, acc_is_new = _upsert_account(db, account_code)
            if acc_is_new:
                new_accounts.append(account_code)

            # グループ upsert
            group: Optional[Group] = None
            if group_code:
                group, grp_is_new = _upsert_group(db, group_code)
                if grp_is_new:
                    new_groups.append(group_code)

            transfer_detail = category_path if is_transfer else None

            tx = Transaction(
                date=tx_date,
                category_id=category.id,
                account_id=account.id,
                income_amount=income,
                expense_amount=expense,
                memo=memo or None,
                group_id=group.id if group else None,
                is_transfer=is_transfer,
                transfer_detail=transfer_detail,
                import_hash=import_hash,
            )
            db.add(tx)
            imported += 1
            all_hashes_this_import.add(import_hash)

        except Exception as e:
            errors += 1
            error_messages.append(f"行{total}: {str(e)}")
            continue

    # ── 対向トランザクション自動生成 ──────────────────────────────────────
    # ファイル内に存在しない（= all_hashes_this_import に含まれない）対向を補完する
    missing_cp_hashes = set(pending_counterparts.keys()) - all_hashes_this_import
    if missing_cp_hashes:
        existing_in_db: set[str] = {
            row[0] for row in
            db.query(Transaction.import_hash)
            .filter(Transaction.import_hash.in_(missing_cp_hashes))
            .all()
        }
        truly_missing = missing_cp_hashes - existing_in_db

        for cp_hash in truly_missing:
            cp = pending_counterparts[cp_hash]
            try:
                cp_date = datetime.strptime(cp["date_str"], "%Y/%m/%d").date()
                cp_cat, cp_cat_new = _upsert_category(db, cp["category_path"])
                if cp_cat_new:
                    new_categories.append(cp["category_path"])
                cp_acc, cp_acc_new = _upsert_account(db, cp["account_code"])
                if cp_acc_new:
                    new_accounts.append(cp["account_code"])
                cp_grp: Optional[Group] = None
                if cp["group_code"]:
                    cp_grp, cp_grp_new = _upsert_group(db, cp["group_code"])
                    if cp_grp_new:
                        new_groups.append(cp["group_code"])

                cp_tx = Transaction(
                    date=cp_date,
                    category_id=cp_cat.id,
                    account_id=cp_acc.id,
                    income_amount=cp["income"],
                    expense_amount=cp["expense"],
                    memo=cp["memo"] or None,
                    group_id=cp_grp.id if cp_grp else None,
                    is_transfer=True,
                    transfer_detail=cp["category_path"],
                    import_hash=cp_hash,
                )
                db.add(cp_tx)
                imported += 1
            except Exception as e:
                errors += 1
                error_messages.append(f"対向生成エラー({cp['category_path']}): {str(e)}")

    # インポートログ保存
    status = "success" if errors == 0 else ("partial" if imported > 0 else "error")
    log = ImportLog(
        filename=filename,
        total_rows=total,
        imported_rows=imported,
        skipped_rows=skipped,
        error_rows=errors,
        status=status,
        error_detail="\n".join(error_messages) if error_messages else None,
    )
    db.add(log)
    db.commit()

    from app.schemas.import_result import SkippedRow
    return ImportResult(
        status=status,
        filename=filename,
        mode=mode,
        total_rows=total,
        imported_rows=imported,
        skipped_rows=skipped,
        skipped_loan_rows=skipped_loan,
        error_rows=errors,
        deleted_rows=deleted_rows,
        new_categories=list(set(new_categories)),
        new_accounts=list(set(new_accounts)),
        new_groups=list(set(new_groups)),
        error_detail="\n".join(error_messages) if error_messages else None,
        skipped_detail=[SkippedRow(**d) for d in skipped_details],
    )
