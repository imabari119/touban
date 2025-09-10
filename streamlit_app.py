import calendar
import io
import zipfile
from datetime import date

import jpholiday
import pandas as pd
import streamlit as st
from ortools.sat.python import cp_model

st.set_page_config(page_title="今治市救急病院 当番表作成ツール", layout="wide")
st.title("救急病院 当番表作成ツール")

# ---------------------
# 年月指定
# ---------------------
st.sidebar.header("設定")
year = st.sidebar.number_input("年 (YYYY)", min_value=2020, max_value=2100, value=date.today().year)
month = st.sidebar.number_input("月 (1-12)", min_value=1, max_value=12, value=date.today().month)

# その月の日数を計算
days_in_month = calendar.monthrange(year, month)[1]

# 日付リスト (YYYY-MM-DD)
dates = pd.date_range(start=f"{year}-{month:02d}-01", periods=days_in_month, freq="D")
date_labels = dates.strftime("%Y-%m-%d").tolist()

# 曜日を日本語に変換
weekday_map = ["月", "火", "水", "木", "金", "土", "日"]
date_display = [
    d.strftime("%m/%d") + f"({weekday_map[d.weekday()] if not jpholiday.is_holiday(d) else '祝'})" for d in dates
]

# ---------------------
# 病院数・病院名
# ---------------------
num_hospitals = st.sidebar.number_input("病院数", min_value=6, max_value=10, value=8)

st.sidebar.subheader("病院名")

hospital_names = []
for i in range(num_hospitals):
    name = st.sidebar.text_input(f"病院 {i} の名前", value=f"Hospital {i}")
    hospital_names.append(name)

# ---------------------
# 割り当て回数
# ---------------------
st.sidebar.subheader("各病院の割当回数")
exact_shifts = {}
for h in hospital_names:
    exact_shifts[h] = st.sidebar.number_input(
        f"{h}",
        min_value=0,
        max_value=days_in_month,
        value=days_in_month // num_hospitals,
    )

# 合計チェック
if sum(exact_shifts.values()) != days_in_month:
    st.sidebar.error(f"回数の合計が {days_in_month} になっていません！（現在: {sum(exact_shifts.values())}）")

# ---------------------
# 非番日入力 (チェックボックス付き)
# ---------------------
st.subheader("非番日の指定")

ng_df = pd.DataFrame(False, index=hospital_names, columns=date_display)

# 編集用
edited_ng_df = st.data_editor(ng_df, width="stretch")

# 非番日辞書に変換（内部では日番号に変換）
ng_days = {}
for h in hospital_names:
    ng_days[h] = [i + 1 for i, val in enumerate(edited_ng_df.loc[h]) if val]

st.sidebar.subheader("パターン")
# 最大パターン数
max_patterns = st.sidebar.number_input("最大パターン数", min_value=1, max_value=50, value=10)

# ---------------------
# スケジュール作成ボタン
# ---------------------
if st.button("当番表を作成"):
    if sum(exact_shifts.values()) != days_in_month:
        st.error("割り当て回数の合計が日数と一致していません！")
    else:
        # OR-Tools モデル定義
        model = cp_model.CpModel()
        x = {}
        for d in range(days_in_month):
            for h in hospital_names:
                x[d, h] = model.NewBoolVar(f"x[{d},{h}]")

        # 各日1病院
        for d in range(days_in_month):
            model.Add(sum(x[d, h] for h in hospital_names) == 1)

        # NG日制約
        for h in hospital_names:
            for d in ng_days[h]:
                model.Add(x[d - 1, h] == 0)

        # 回数制約
        for h in hospital_names:
            model.Add(sum(x[d, h] for d in range(days_in_month)) == exact_shifts[h])

        # 勤務間隔 >= 4日
        for h in hospital_names:
            for d in range(days_in_month - 3):
                model.Add(x[d, h] + x[d + 1, h] + x[d + 2, h] + x[d + 3, h] <= 1)

        class SolutionCollector(cp_model.CpSolverSolutionCallback):
            def __init__(self, x, hospitals, days, max_solutions):
                cp_model.CpSolverSolutionCallback.__init__(self)
                self._x = x
                self._hospitals = hospitals
                self._days = days
                self._max_solutions = max_solutions
                self.solutions = []
                self._solution_count = 0

            def on_solution_callback(self):
                if self._solution_count >= self._max_solutions:
                    self.StopSearch()
                    return

                result = []
                for d in range(self._days):
                    for h in self._hospitals:
                        if self.Value(self._x[d, h]) == 1:
                            result.append(h)
                self.solutions.append(result)
                self._solution_count += 1

        # 解探索
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 20

        collector = SolutionCollector(x, hospital_names, days_in_month, max_patterns)
        solver.SearchForAllSolutions(model, collector)

        if collector.solutions:
            st.success(f"{len(collector.solutions)} パターンの当番表が見つかりました！")

            csv_files = {}

            # 複数解をタブで表示
            tabs = st.tabs([f"案 {i + 1}" for i in range(len(collector.solutions))])

            for i, sol in enumerate(collector.solutions):
                with tabs[i]:
                    schedule_df = pd.DataFrame({"日付": date_labels, "担当病院": sol})
                    st.dataframe(schedule_df, use_container_width=True)

                    # CSV ダウンロード
                    csv_bytes = io.BytesIO()
                    csv_bytes.write(schedule_df.to_csv(index=False).encode("utf-8-sig"))
                    csv_bytes.seek(0)

                    file_name = f"hospital_schedule_{year}_{month}_pattern{i + 1}.csv"
                    st.download_button(
                        label=f"📥 パターン {i + 1} をCSVでダウンロード",
                        data=csv_bytes,
                        file_name=file_name,
                        mime="text/csv",
                    )

                    # zip 用に保存
                    csv_files[file_name] = csv_bytes.getvalue()

            # ---------------------
            # すべて zip にまとめる
            # ---------------------
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file_name, csv_data in csv_files.items():
                    zipf.writestr(file_name, csv_data)

            st.download_button(
                label="📦 すべてのパターンをZIPで一括ダウンロード",
                data=zip_buffer.getvalue(),
                file_name=f"hospital_schedules_{year}_{month}.zip",
                mime="application/zip",
            )

        else:
            st.error("解が見つかりませんでした。条件を見直してください。")
