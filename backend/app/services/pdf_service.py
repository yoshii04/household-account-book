"""前月末時点の全レポートを 1 PDF にまとめて生成するサービス（親カテゴリのみ・グラフ付き）"""
import calendar
import io
from datetime import date

from app.jst import today_jst

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import ParagraphStyle
from sqlalchemy.orm import Session

from app.services.report_service import (
    get_account_balance_report,
    get_comparison,
    get_matrix_report,
    get_monthly_summary,
)

pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
_FONT = "HeiseiKakuGo-W5"
_PAGE_W = float(A4[0] - 30 * mm)  # コンテンツ幅 ≈ 510 pt

_PALETTE = [
    colors.HexColor(c) for c in [
        "#4472C4", "#ED7D31", "#A9D18E", "#FF6384", "#FFCE56",
        "#4BC0C0", "#9966FF", "#FF9F40", "#C9CBCF", "#7BC8A4",
    ]
]

# ─── ユーティリティ ────────────────────────────────────────────────────────────


def _fmt(n) -> str:
    n = int(n or 0)
    return f"¥{n:,}" if n != 0 else "—"


def _pct(r) -> str:
    if r is None:
        return "—"
    sign = "+" if r >= 0 else ""
    return f"{sign}{r:.1f}%"


def _diff(n) -> str:
    n = int(n or 0)
    if n == 0:
        return "—"
    sign = "+" if n > 0 else ""
    return f"{sign}¥{n:,}"


def _trunc(s: str, n: int = 10) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _compact_val(v: float) -> str:
    v = int(v or 0)
    if v >= 10_000_000:
        return f"{v // 1_000_000}百万"
    if v >= 100_000:
        return f"{v // 10_000}万"
    if v >= 1_000:
        return f"{v // 1_000}千"
    return str(v)


def _style(name: str, **kw) -> ParagraphStyle:
    return ParagraphStyle(name=name, fontName=_FONT, **kw)


def _h1(text: str) -> Paragraph:
    return Paragraph(
        text,
        _style("h1", fontSize=16, spaceAfter=4, leading=22, textColor=colors.HexColor("#1a1a2e")),
    )


def _h2(text: str) -> Paragraph:
    return Paragraph(
        text,
        _style("h2", fontSize=12, spaceAfter=3, leading=17, textColor=colors.HexColor("#2c3e50")),
    )


def _p(text: str) -> Paragraph:
    return Paragraph(text, _style("p", fontSize=9, leading=13))


def _base_table_style(extra: list | None = None) -> TableStyle:
    cmds = [
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if extra:
        cmds.extend(extra)
    return TableStyle(cmds)


def _section_header_styles(rows: list) -> list:
    extra = []
    for i, row in enumerate(rows):
        first = row[0] if row else ""
        if isinstance(first, str) and first.startswith("──"):
            extra.extend([
                ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#E8ECEF")),
                ("ALIGN", (0, i), (-1, i), "LEFT"),
            ])
    return extra


# ─── グラフ生成 ────────────────────────────────────────────────────────────────


def _make_hbar_chart(
    labels: list[str],
    values: list[int],
    w: float = _PAGE_W,
    h: float = 200.0,
) -> Drawing:
    """横棒グラフ（単一系列）"""
    d = Drawing(w, h)
    if not values or all(v == 0 for v in values):
        return d

    label_w = 140.0
    chart = HorizontalBarChart()
    chart.x = label_w
    chart.y = 20.0
    chart.width = w - label_w - 15.0
    chart.height = h - 30.0

    chart.data = [values]
    chart.categoryAxis.categoryNames = [_trunc(lb) for lb in labels]
    chart.categoryAxis.labels.fontName = _FONT
    chart.categoryAxis.labels.fontSize = 8
    chart.categoryAxis.labels.boxAnchor = "e"
    chart.categoryAxis.labels.dx = -4

    chart.valueAxis.labels.fontName = _FONT
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.valueMin = 0
    chart.valueAxis.labelTextFormat = _compact_val

    chart.bars[0].fillColor = _PALETTE[0]
    d.add(chart)
    return d


def _make_comparison_hbar(
    labels: list[str],
    this_values: list[int],
    last_values: list[int],
    year: int,
    last_year: int,
    w: float = _PAGE_W,
    h: float = 230.0,
) -> Drawing:
    """今年vs前年 グループ横棒グラフ"""
    d = Drawing(w, h)
    if not this_values and not last_values:
        return d

    label_w = 140.0
    legend_w = 70.0
    chart = HorizontalBarChart()
    chart.x = label_w
    chart.y = 20.0
    chart.width = w - label_w - legend_w - 10.0
    chart.height = h - 30.0

    chart.data = [this_values, last_values]
    chart.categoryAxis.categoryNames = [_trunc(lb) for lb in labels]
    chart.categoryAxis.labels.fontName = _FONT
    chart.categoryAxis.labels.fontSize = 8
    chart.categoryAxis.labels.boxAnchor = "e"
    chart.categoryAxis.labels.dx = -4

    chart.valueAxis.labels.fontName = _FONT
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.valueMin = 0
    chart.valueAxis.labelTextFormat = _compact_val

    chart.bars[0].fillColor = _PALETTE[0]
    chart.bars[1].fillColor = _PALETTE[2]

    d.add(chart)

    # 凡例
    leg = Legend()
    leg.colorNamePairs = [
        (_PALETTE[0], str(year)),
        (_PALETTE[2], str(last_year)),
    ]
    leg.fontName = _FONT
    leg.fontSize = 8
    leg.x = chart.x + chart.width + 8
    leg.y = chart.y + chart.height - 20
    leg.deltax = 10
    leg.deltay = 14
    leg.columnMaximum = 2
    d.add(leg)
    return d


def _make_pie_chart(
    labels: list[str],
    values: list[int],
    w: float = _PAGE_W,
    h: float = 200.0,
) -> Drawing:
    """円グラフ"""
    d = Drawing(w, h)
    pos_vals = [(lb, v) for lb, v in zip(labels, values) if v > 0]
    if not pos_vals:
        return d

    labels_f, values_f = zip(*pos_vals)
    total = sum(values_f)

    pie = Pie()
    pie.x = 20
    pie.y = 10
    pie.width = min(h - 20, w * 0.45)
    pie.height = pie.width
    pie.data = list(values_f)
    pie.labels = [f"{lb}\n{v / total * 100:.1f}%" for lb, v in zip(labels_f, values_f)]

    pie.sideLabels = True
    pie.sideLabelsOffset = 0.1
    pie.simpleLabels = False

    for i in range(len(values_f)):
        pie.slices[i].fillColor = _PALETTE[i % len(_PALETTE)]
        pie.slices[i].fontName = _FONT
        pie.slices[i].fontSize = 7

    d.add(pie)

    # テキスト凡例
    leg_x = pie.x + pie.width + 30
    leg_y = pie.y + pie.height
    for i, (lb, v) in enumerate(zip(labels_f, values_f)):
        y_pos = leg_y - i * 18
        if y_pos < pie.y:
            break
        d.add(Rect(leg_x, y_pos - 6, 10, 8,
                   fillColor=_PALETTE[i % len(_PALETTE)],
                   strokeColor=colors.white))
        label_str = f"{_trunc(lb, 8)}  {_fmt(v)}"
        s = String(leg_x + 14, y_pos - 4, label_str,
                   fontName=_FONT, fontSize=8)
        d.add(s)

    return d


# ─── 月次集計 ──────────────────────────────────────────────────────────────────


def _build_monthly(monthly: dict, story: list) -> None:
    year, month = monthly["year"], monthly["month"]
    story.append(_h2(f"■ {year}年{month}月  費目別月次集計"))
    story.append(Spacer(1, 3 * mm))

    total_in = monthly["total_income"]
    total_ex = monthly["total_expense"]
    balance = total_in - total_ex
    bal_color = colors.HexColor("#1a7741") if balance >= 0 else colors.HexColor("#c0392b")

    summary_data = [
        ["収入合計", "支出合計", "差引"],
        [_fmt(total_in), _fmt(total_ex), _fmt(balance)],
    ]
    t = Table(summary_data, colWidths=[_PAGE_W / 3] * 3)
    t.setStyle(_base_table_style([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 1), (-1, 1), 11),
        ("TEXTCOLOR", (2, 1), (2, 1), bal_color),
    ]))
    story.append(t)
    story.append(Spacer(1, 4 * mm))

    # 費目別テーブル（親カテゴリのみ）
    rows = [["費目", "収入", "支出"]]
    for section_cats, label in [
        (monthly["income_categories"], "── 収入 ──"),
        (monthly["expense_categories"], "── 支出 ──"),
    ]:
        if section_cats:
            rows.append([label, "", ""])
            for cat in section_cats:
                rows.append([
                    cat["name"],
                    _fmt(cat["total_income"]) if cat["total_income"] else "—",
                    _fmt(cat["total_expense"]) if cat["total_expense"] else "—",
                ])

    col_w = [_PAGE_W * 0.52, _PAGE_W * 0.24, _PAGE_W * 0.24]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(_base_table_style(_section_header_styles(rows)))
    story.append(t)
    story.append(Spacer(1, 5 * mm))

    # グラフ：支出カテゴリ Top10 横棒グラフ
    exp_sorted = sorted(
        [c for c in monthly["expense_categories"] if c["total_expense"] > 0],
        key=lambda c: c["total_expense"],
        reverse=True,
    )[:10]
    if exp_sorted:
        story.append(_p("【支出カテゴリ Top10】"))
        story.append(Spacer(1, 2 * mm))
        labels = [c["name"] for c in reversed(exp_sorted)]
        values = [c["total_expense"] for c in reversed(exp_sorted)]
        bar_h = max(150.0, len(labels) * 22.0 + 30.0)
        story.append(_make_hbar_chart(labels, values, _PAGE_W, bar_h))

    # グラフ：収入・支出の構成 円グラフ
    inc_sorted = sorted(
        [c for c in monthly["income_categories"] if c["total_income"] > 0],
        key=lambda c: c["total_income"],
        reverse=True,
    )
    if inc_sorted:
        story.append(Spacer(1, 5 * mm))
        story.append(_p("【収入カテゴリ 構成】"))
        story.append(Spacer(1, 2 * mm))
        story.append(_make_pie_chart(
            [c["name"] for c in inc_sorted],
            [c["total_income"] for c in inc_sorted],
            _PAGE_W, 180.0,
        ))


# ─── 前年同月比 ────────────────────────────────────────────────────────────────


def _build_comparison(data: dict, story: list) -> None:
    year, month = data["year"], data["month"]
    last_year = data["last_year"]

    story.append(_h2(f"■ {year}年{month}月  前年同月比（vs {last_year}年）"))
    story.append(Spacer(1, 3 * mm))

    summary_data = [
        ["", f"{year}年", f"{last_year}年", "差額"],
        ["収入計",
         _fmt(data["total_this_income"]), _fmt(data["total_last_income"]),
         _diff(data["diff_income"])],
        ["支出計",
         _fmt(data["total_this_expense"]), _fmt(data["total_last_expense"]),
         _diff(data["diff_expense_total"])],
        ["差引",
         _fmt(data["total_this_balance"]), _fmt(data["total_last_balance"]),
         _diff(data["diff_balance"])],
    ]
    t = Table(summary_data, colWidths=[_PAGE_W * 0.28] + [_PAGE_W * 0.24] * 3)
    t.setStyle(_base_table_style())
    story.append(t)
    story.append(Spacer(1, 4 * mm))

    # 費目別テーブル（親カテゴリのみ）
    rows = [["費目", f"{year}年", f"{last_year}年", "差額", "増減率"]]
    for section_cats, label in [
        (data["income_categories"], "── 収入 ──"),
        (data["expense_categories"], "── 支出 ──"),
    ]:
        if section_cats:
            rows.append([label, "", "", "", ""])
            for cat in section_cats:
                this_val = cat["this_year_income"] if cat["this_year_income"] > 0 else cat["this_year_expense"]
                last_val = cat["last_year_income"] if cat["last_year_income"] > 0 else cat["last_year_expense"]
                diff_val = cat["diff_income"] if cat["this_year_income"] > 0 else cat["diff_expense"]
                ratio_val = cat["ratio_income"] if cat["this_year_income"] > 0 else cat["ratio_expense"]
                rows.append([
                    cat["name"],
                    _fmt(this_val),
                    _fmt(last_val),
                    _diff(diff_val),
                    _pct(ratio_val),
                ])

    col_w = [_PAGE_W * 0.35, _PAGE_W * 0.16, _PAGE_W * 0.16, _PAGE_W * 0.17, _PAGE_W * 0.16]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(_base_table_style(_section_header_styles(rows)))
    story.append(t)
    story.append(Spacer(1, 5 * mm))

    # グラフ：支出 今年 vs 前年 横棒グラフ（Top8）
    exp_cats = sorted(
        [c for c in data["expense_categories"] if c["this_year_expense"] > 0 or c["last_year_expense"] > 0],
        key=lambda c: c["this_year_expense"],
        reverse=True,
    )[:8]
    if exp_cats:
        story.append(_p("【支出 前年同月比 Top8】"))
        story.append(Spacer(1, 2 * mm))
        labels = [c["name"] for c in reversed(exp_cats)]
        this_vals = [c["this_year_expense"] for c in reversed(exp_cats)]
        last_vals = [c["last_year_expense"] for c in reversed(exp_cats)]
        bar_h = max(160.0, len(labels) * 28.0 + 30.0)
        story.append(_make_comparison_hbar(labels, this_vals, last_vals, year, last_year, _PAGE_W, bar_h))


# ─── カテゴリ×グループ マトリックス ──────────────────────────────────────────


def _build_matrix(data: dict, story: list) -> None:
    year, month = data["year"], data["month"]
    story.append(_h2(f"■ {year}年{month}月  カテゴリ×グループ マトリックス"))
    story.append(Spacer(1, 3 * mm))

    groups = data["groups"]
    has_no_group = data["has_no_group"]
    n_extra = len(groups) + (1 if has_no_group else 0) + 1  # グループ数 + 合計列

    header = ["費目"] + [g["name"] for g in groups]
    if has_no_group:
        header.append("(未分類)")
    header.append("合計")

    name_w = _PAGE_W * 0.35
    extra_w = (_PAGE_W - name_w) / n_extra if n_extra else _PAGE_W - name_w
    col_w = [name_w] + [extra_w] * n_extra
    font_sz = max(6, 8 - max(0, n_extra - 4))

    def _row(cat: dict) -> list:
        cells = cat.get("cells", {})
        row = [cat["name"]]
        for g in groups:
            row.append(_fmt(cells.get(g["id"], 0)) if cells.get(g["id"]) else "—")
        if has_no_group:
            row.append(_fmt(cells.get(None, 0)) if cells.get(None) else "—")
        row.append(_fmt(cat["row_total"]) if cat["row_total"] else "—")
        return row

    rows = [header]
    for section_cats, label in [
        (data["income_categories"], "── 収入 ──"),
        (data["expense_categories"], "── 支出 ──"),
    ]:
        if section_cats:
            rows.append([label] + [""] * n_extra)
            for cat in section_cats:
                rows.append(_row(cat))

    # 支出合計行
    rows.append(
        ["支出合計"]
        + [_fmt(data["expense_col_totals"].get(g["id"], 0)) for g in groups]
        + ([_fmt(data["expense_col_totals"].get(None, 0))] if has_no_group else [])
        + [_fmt(data["expense_grand_total"])]
    )

    total_idx = len(rows) - 1
    extra = _section_header_styles(rows)
    extra.extend([
        ("FONTSIZE", (0, 0), (-1, -1), font_sz),
        ("BACKGROUND", (0, total_idx), (-1, total_idx), colors.HexColor("#D6E4F7")),
    ])
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(_base_table_style(extra))
    story.append(t)


# ─── アカウント別残高 ──────────────────────────────────────────────────────────


def _build_account_balance(data: dict, story: list) -> None:
    as_of = data["as_of_date"]
    story.append(_h2(f"■ {as_of} 時点  アカウント別残高"))
    story.append(Spacer(1, 3 * mm))

    rows = [["種別 / アカウント", "初期残高", "調整", "入金計", "出金計", "残高"]]
    for grp in data["grouped"]:
        rows.append([f"【{grp['type_label']}】", "", "", "", "", ""])
        for acc in grp["accounts"]:
            rows.append([
                acc["name"],
                _fmt(acc["initial_balance"]) if acc["initial_balance"] else "—",
                _fmt(acc["adjustment_amount"]) if acc["adjustment_amount"] else "—",
                _fmt(acc["total_income"]) if acc["total_income"] else "—",
                _fmt(acc["total_expense"]) if acc["total_expense"] else "—",
                _fmt(acc["balance"]),
            ])
        rows.append([
            f"  {grp['type_label']} 小計",
            _fmt(grp["subtotal_initial"]) if grp["subtotal_initial"] else "—",
            _fmt(grp["subtotal_adjustment"]) if grp["subtotal_adjustment"] else "—",
            _fmt(grp["subtotal_income"]) if grp["subtotal_income"] else "—",
            _fmt(grp["subtotal_expense"]) if grp["subtotal_expense"] else "—",
            _fmt(grp["subtotal_balance"]),
        ])

    rows.append([
        "合計",
        _fmt(data["grand_initial"]) if data["grand_initial"] else "—",
        _fmt(data["grand_adjustment"]) if data["grand_adjustment"] else "—",
        _fmt(data["grand_income"]) if data["grand_income"] else "—",
        _fmt(data["grand_expense"]) if data["grand_expense"] else "—",
        _fmt(data["grand_balance"]),
    ])

    col_w = [_PAGE_W * 0.30, _PAGE_W * 0.14, _PAGE_W * 0.12,
             _PAGE_W * 0.14, _PAGE_W * 0.14, _PAGE_W * 0.16]

    extra = []
    for i, row in enumerate(rows):
        first = row[0] if row else ""
        if isinstance(first, str) and first.startswith("【"):
            extra.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#E8ECEF")))
        elif isinstance(first, str) and "小計" in first:
            extra.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#EBF2FA")))

    total_idx = len(rows) - 1
    extra.append(("BACKGROUND", (0, total_idx), (-1, total_idx), colors.HexColor("#D6E4F7")))

    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(_base_table_style(extra))
    story.append(t)
    story.append(Spacer(1, 5 * mm))

    # グラフ：口座種別残高 円グラフ（マイナス残高は絶対値で表示し凡例に負債と表記）
    pie_entries = [(grp["type_label"], grp["subtotal_balance"]) for grp in data["grouped"] if grp["subtotal_balance"] != 0]
    if pie_entries:
        pie_labels = [lb if v >= 0 else f"{lb}(負債)" for lb, v in pie_entries]
        pie_values = [abs(v) for _, v in pie_entries]
        story.append(_p("【口座種別 残高構成】"))
        story.append(Spacer(1, 2 * mm))
        story.append(_make_pie_chart(pie_labels, pie_values, _PAGE_W, 190.0))


# ─── PDF 生成メイン ────────────────────────────────────────────────────────────


def generate_monthly_report_pdf(db: Session, year: int, month: int) -> tuple[bytes, str]:
    """
    指定年月の全レポートをまとめた PDF を生成する。
    戻り値: (pdf_bytes, filename)
    """
    last_day = calendar.monthrange(year, month)[1]
    as_of_date = date(year, month, last_day)
    filename = f"{year}{month:02d}{last_day:02d}時点収支レポート.pdf"

    monthly = get_monthly_summary(db, year, month)
    comp = get_comparison(db, year, month)
    matrix = get_matrix_report(db, year, month)
    balance = get_account_balance_report(db, as_of_date)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    story: list = []

    # カバーページ
    story.append(Spacer(1, 20 * mm))
    story.append(_h1(f"家計簿レポート  {year}年{month}月"))
    story.append(Spacer(1, 3 * mm))
    story.append(_p(f"作成日: {today_jst().strftime('%Y年%m月%d日')}　　対象期間末: {as_of_date.strftime('%Y年%m月%d日')}"))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#4472C4"), spaceAfter=8 * mm))
    story.append(_p("【収録レポート】"))
    story.append(_p("　1. 費目別月次集計（親カテゴリ）＋ グラフ"))
    story.append(_p("　2. 前年同月比（親カテゴリ）＋ グラフ"))
    story.append(_p("　3. カテゴリ×グループ マトリックス（親カテゴリ）"))
    story.append(_p("　4. アカウント別残高 ＋ グラフ"))
    story.append(PageBreak())

    _build_monthly(monthly, story)
    story.append(PageBreak())

    _build_comparison(comp, story)
    story.append(PageBreak())

    _build_matrix(matrix, story)
    story.append(PageBreak())

    _build_account_balance(balance, story)

    doc.build(story)
    buf.seek(0)
    return buf.read(), filename
