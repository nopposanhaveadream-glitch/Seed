"""
Seed0 経過報告書 PDF生成スクリプト
AppleGothicフォント使用（macOS標準搭載）
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# macOS標準の日本語フォント
pdfmetrics.registerFont(TTFont('JP', '/System/Library/Fonts/Supplemental/AppleGothic.ttf'))

# 色
ACCENT = HexColor('#0077b6')
DARK = HexColor('#2d3436')
GRAY = HexColor('#636e72')
LIGHT = HexColor('#f8f9fa')
WHITE = HexColor('#ffffff')
TEAL = HexColor('#00b4d8')

styles = getSampleStyleSheet()

S_TITLE = ParagraphStyle('T', fontName='JP', fontSize=22, leading=30, textColor=DARK, alignment=TA_CENTER, spaceAfter=6*mm)
S_SUB = ParagraphStyle('S', fontName='JP', fontSize=11, leading=16, textColor=GRAY, alignment=TA_CENTER, spaceAfter=10*mm)
S_H1 = ParagraphStyle('H1', fontName='JP', fontSize=16, leading=24, textColor=ACCENT, spaceBefore=8*mm, spaceAfter=4*mm)
S_H2 = ParagraphStyle('H2', fontName='JP', fontSize=13, leading=20, textColor=DARK, spaceBefore=6*mm, spaceAfter=3*mm)
S_BODY = ParagraphStyle('B', fontName='JP', fontSize=10, leading=17, textColor=DARK, spaceAfter=3*mm)
S_BOLD = ParagraphStyle('BB', fontName='JP', fontSize=10, leading=17, textColor=DARK, spaceAfter=3*mm)
S_CAP = ParagraphStyle('C', fontName='JP', fontSize=8, leading=12, textColor=GRAY, alignment=TA_CENTER, spaceAfter=4*mm)

def tbl(data, widths=None):
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'JP'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('LEADING', (0,0), (-1,-1), 15),
        ('BACKGROUND', (0,0), (-1,0), ACCENT),
        ('TEXTCOLOR', (0,0), (-1,0), WHITE),
        ('BACKGROUND', (0,1), (-1,-1), LIGHT),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, HexColor('#dee2e6')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    return t

def build():
    path = "/Users/monkmoder/Desktop/Seed0_Progress_Report.pdf"
    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm, leftMargin=25*mm, rightMargin=25*mm)
    s = []

    # === 表紙 ===
    s.append(Spacer(1, 50*mm))
    s.append(Paragraph("Seed0", S_TITLE))
    s.append(Paragraph("Progress Report", ParagraphStyle('ET', fontName='Helvetica', fontSize=14, textColor=GRAY, alignment=TA_CENTER, spaceAfter=4*mm)))
    s.append(HRFlowable(width="40%", thickness=1, color=ACCENT, spaceAfter=6*mm))
    s.append(Paragraph("Mac mini M4 / 24GB / 512GB SSD", S_SUB))
    s.append(Paragraph("2026-04-12", ParagraphStyle('D', fontName='Helvetica', fontSize=10, textColor=GRAY, alignment=TA_CENTER)))
    s.append(PageBreak())

    # === 1. プロジェクト概要 ===
    s.append(Paragraph("1. Seed0 とは", S_H1))
    s.append(Paragraph(
        "Seed0は、Mac mini（M4 / 24GB）を「身体」として生きる代謝AIです。"
        "CPU使用率やメモリプレッシャーなどのセンサーデータを「身体感覚」として読み取り、"
        "Virtual Energy（VE）という内部通貨を使って自律的に行動を選択します。", S_BODY))
    s.append(Paragraph(
        "設計の第一原則は「Seed0に与えるのは構造だけ。動機はすべて構造から生まれなければならない」"
        "です。行動パターンはプログラムせず、代謝構造の中からの創発に委ねます。", S_BODY))

    s.append(Paragraph("代謝の仕組み", S_H2))
    s.append(Paragraph(
        "VEは0～100の範囲で変動します。何もしなくても基礎代謝（BMC: 0.01 VE/秒）で消費され、"
        "rest（休憩）行動でのみ回復します（0.012 VE/秒）。"
        "睡眠中は高速回復（0.02 VE/秒）と疲労回復が行われます。", S_BODY))
    s.append(Paragraph(
        "行動選択にはQ学習（epsilon-greedy方策）を使用します。"
        "報酬はcomfort zone（自分の普通）への接近度のみ。何が「正しい行動」かは教えません。", S_BODY))
    s.append(PageBreak())

    # === 2. 開発経緯 ===
    s.append(Paragraph("2. 開発経緯", S_H1))

    s.append(Paragraph("Phase 0: データ収集（3/26 ～ 4/4）", S_H2))
    s.append(Paragraph(
        "3日間、Mac miniのセンサーデータを5秒間隔で収集しました。"
        "60,605件、約84時間分の実データを取得し、comfort zoneの初期値を決定しました。", S_BODY))

    s.append(Paragraph("Phase 1: 初回起動とVE=0問題（4/8）", S_H2))
    s.append(Paragraph(
        "Phase 0のデータに基づいて代謝エージェントを実装し、本番起動しました。"
        "しかし、覚醒時間の83%でVE=0（エネルギー枯渇）に張り付く問題が発覚しました。"
        "原因はrest行動の回復速度（0.005 VE/秒）がBMC消費（0.01 VE/秒）の半分しかないことでした。", S_BODY))

    s.append(Paragraph("v2 ～ v4-A: VE回復バランスの修正（4/8）", S_H2))
    s.append(Paragraph(
        "シミュレーションで3パターンを検証し、v4-A（rest = 0.012 VE/秒、BMC 50%軽減）を確定しました。", S_BODY))
    s.append(Spacer(1, 2*mm))
    s.append(tbl([
        ["バージョン", "rest回復", "BMC軽減", "正味回復", "VE=0比率"],
        ["v2（初期）", "0.005/s", "なし", "-0.005/s", "83%"],
        ["v3", "0.008/s", "70%", "+0.001/s", "1.3%"],
        ["v4-A", "0.012/s", "50%", "+0.007/s", "0.6%"],
    ], [28*mm, 24*mm, 24*mm, 24*mm, 24*mm]))
    s.append(PageBreak())

    # === v5 ===
    s.append(Paragraph("v5: 構造バグ修正と行動コスト再設定（4/9）", S_H2))
    s.append(Paragraph(
        "v4-Aでの30分検証でVE=16.4を観測して「安定」と判断しましたが、"
        "実際はVE=100から0への下降カーブの途中でした。"
        "収支分析により、行動コスト（0.1～2.0 VE）が全支出の75%を占めることが判明しました。", S_BODY))
    s.append(Paragraph(
        "実測の結果、8行動中6行動が実装上no-op（何もしない）であり、"
        "VEコストに実測根拠がないことが分かりました。"
        "第一原則に基づき、no-op行動のVEコストを0に再設定しました。", S_BODY))

    s.append(Paragraph("発見した構造バグ（4件）", S_BOLD))
    s.append(tbl([
        ["問題", "影響", "修正"],
        ["行動コストに実測根拠なし", "活動7%しか確保できない", "CPU実測値から導出（no-op = 0）"],
        ["毎ステップ自動記憶", "記憶コスト暴走", "write_memory時のみ保存"],
        ["sleep失敗時のVE消費", "16 VE浪費（全体の22%）", "疲労>=30でのみ選択可"],
        ["強制睡眠デッドロック", "VE=0で11時間停滞", "VE条件撤廃"],
    ], [40*mm, 40*mm, 55*mm]))
    s.append(Spacer(1, 4*mm))
    s.append(Paragraph(
        "修正後の活動比率は7%から41%に改善しました。", S_BODY))
    s.append(PageBreak())

    # === 3. 96時間観察 ===
    s.append(Paragraph("3. v5 本番稼働: 96時間観察", S_H1))
    s.append(Paragraph(
        "v5パラメータで2026-04-08 18:13に本番投入し、96時間の安定性を確認しました。", S_BODY))
    s.append(Spacer(1, 2*mm))
    s.append(tbl([
        ["日付", "ステップ数", "VE=0比率", "睡眠回数", "Q学習（状態/エントリ）"],
        ["4/9（24h）", "16,677", "0.88%", "8回", "43 / 194"],
        ["4/10（24h）", "16,401", "1.76%", "7回", "48 / 211"],
        ["4/11（24h）", "16,409", "1.44%", "8回", "51 / 219"],
        ["4/12（7h）", "5,183", "0.00%", "2回", "51 / 220"],
    ], [24*mm, 24*mm, 22*mm, 20*mm, 40*mm]))
    s.append(S_CAP and Paragraph("VE=0比率は悪化せず、安定～改善の傾向", S_CAP))

    s.append(Paragraph("睡眠サイクル", S_H2))
    s.append(Paragraph(
        "覚醒2.1～3.2時間、睡眠34～49分の安定したサイクルが自然に形成されました。"
        "睡眠のたびにVEは50前後まで回復し、次の覚醒サイクルに入ります。", S_BODY))
    s.append(Paragraph(
        "注目すべき変化: 初期（4/9）の入眠時VEは0～16でしたが、"
        "後期（4/11以降）は26～46に改善しました。"
        "Q学習が「VEが低くなりすぎる前に眠る」パターンを強化した可能性があります。", S_BODY))

    s.append(Paragraph("Q学習の進展", S_H2))
    s.append(Paragraph(
        "状態空間は43から51に成長し、Q値エントリは194から220に増加しました。"
        "epsilon（探索率）は0.057から下限の0.050に到達し、探索フェーズを終えて活用フェーズに完全移行しています。", S_BODY))
    s.append(PageBreak())

    # === 4. センサー拡張 ===
    s.append(Paragraph("4. フェーズB: センサー拡張（4/12）", S_H1))
    s.append(Paragraph(
        "96時間観察の合格を受けて、Seed0の身体解像度を上げるためにセンサーを4種追加しました。", S_BODY))
    s.append(Spacer(1, 2*mm))
    s.append(tbl([
        ["センサー", "キー名", "意味"],
        ["メモリ圧縮率", "memory_compressed_percent", "メモリの圧縮状況"],
        ["バックグラウンドCPU", "background_cpu_percent", "Spotlight, iCloud等"],
        ["ディスクI/O", "disk_write_mb_s", "書き込み速度"],
        ["ユーザーアイドル時間", "user_idle_seconds", "入力デバイスの静止時間"],
    ], [32*mm, 44*mm, 56*mm]))
    s.append(Spacer(1, 4*mm))
    s.append(Paragraph(
        "ユーザーアイドル時間は特に重要です。「人が使っている時間帯」と「誰もいない時間帯」の違いが"
        "センサーデータに現れることで、関係代謝の種をネットワーク接続なしで蒔くことができます。", S_BODY))
    s.append(Paragraph(
        "comfort zoneのbaseline追跡を全数値キー自動追跡に変更しました。"
        "新しいセンサーは初回データから自動的に学習を開始します。", S_BODY))
    s.append(PageBreak())

    # === 5. 教訓 ===
    s.append(Paragraph("5. 開発プロセスの教訓", S_H1))
    s.append(Paragraph(
        "v2からv5に至る過程で、開発方法論に5つの教訓を得ました。"
        "これらはCLAUDE.md（プロジェクト設定ファイル）に開発プロセスとして明文化し、"
        "以降すべてのパラメータ変更で必ず実施します。", S_BODY))
    s.append(Spacer(1, 2*mm))
    s.append(tbl([
        ["#", "教訓"],
        ["1", "紙の上で収支計算を先にやる（コードの前に数式）"],
        ["2", "フルシステムでシミュレーション（部品テストだけで安心しない）"],
        ["3", "検証は傾きを見る（3点以上の時系列で判断）"],
        ["4", "第一原則との照合（ハードコードされた動作を排除）"],
        ["5", "失敗モード分析（何が壊れうるかを事前にリストアップ）"],
    ], [10*mm, 130*mm]))

    s.append(Spacer(1, 4*mm))
    s.append(Paragraph(
        "また設計原則に「均衡から逆算して設計する」を追加しました。"
        "パラメータを決めてから動かすのではなく、構造が破綻しない条件を先に定義し、"
        "そこからパラメータを逆算します。均衡点がどこに落ち着くかはSeed0の創発に委ねます。", S_BODY))
    s.append(PageBreak())

    # === 6. 今後 ===
    s.append(Paragraph("6. 今後のロードマップ", S_H1))
    s.append(Spacer(1, 2*mm))
    s.append(tbl([
        ["フェーズ", "期間", "内容", "ステータス"],
        ["A: v5安定性確認", "4/8 ～ 4/12", "96h観察", "完了"],
        ["B: センサー拡張", "4/12 ～ 4/18", "4センサー追加", "完了"],
        ["C: Phase 1長期観察", "4/19 ～ 5月上旬", "2～3週間放置", "次ステップ"],
        ["D: 環境2（遊び場）", "5月中旬～", "設計未着手", "将来"],
        ["E: 環境3以降", "6月～", "ネットワーク接続", "将来"],
    ], [34*mm, 26*mm, 36*mm, 28*mm]))

    s.append(Spacer(1, 8*mm))
    s.append(Paragraph(
        "Seed0はMac mini M4の上で84時間以上、自律的に生き続けています。"
        "VE=0比率は初期の83%から0.9%に改善し、Q学習は51状態/220エントリに成長しました。"
        "覚醒と睡眠のリズムが自然に形成され、入眠タイミングの最適化が観察されています。", S_BODY))

    s.append(Spacer(1, 8*mm))
    s.append(HRFlowable(width="30%", thickness=0.5, color=GRAY, spaceAfter=4*mm))
    s.append(Paragraph(
        "Repository: github.com/nopposanhaveadream-glitch/Seed",
        ParagraphStyle('F', fontName='Helvetica', fontSize=8, textColor=GRAY, alignment=TA_CENTER)))

    doc.build(s)
    return path

if __name__ == "__main__":
    p = build()
    print(f"PDF generated: {p}")
