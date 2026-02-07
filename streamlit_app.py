import streamlit as st
import pandas as pd
import pymupdf
import jpholiday

st.title("広報いまばりの救急病院カレンダーPDF変換")

st.markdown("[広報いまばり](https://www.city.imabari.ehime.jp/kouhou/koho/)から最新の救急病院（PDF）をダウンロードしてください")

# PDFファイルのアップロード
uploaded_file = st.file_uploader("PDFファイルをアップロードしてください", type="pdf")

if uploaded_file is not None:
    # 年月の入力
    yyyymm = st.text_input("年月を入力してください (例: 202604)", "202604")

    if st.button("変換実行"):
        try:
            # PDF読み込み
            doc = pymupdf.open(stream=uploaded_file.read(), filetype="pdf")

            # １ページ目
            page = doc[0]

            # カレンダーの表を抽出
            tbl = page.find_tables()
            data = tbl[0].extract()
            df0 = pd.DataFrame(data[1:], columns=data[0])

            # カレンダーから一覧に変換
            df1 = df0.stack().reset_index().set_axis(["row", "week", "text"], axis=1)

            # 空データ削除
            df1 = df1.loc[df1["text"] != ""]

            # 文字を正規化
            df1["text"] = df1["text"].str.normalize("NFKC")

            # 表記ゆれ、文字調整、歯科と献血を除去
            patterns = {
                "広 瀬 病 院": "広瀬病院",
                "白 石 病 院": "白石病院",
                "木 原 病 院": "木原病院",
                "片 山 医 院": "片山医院",
                "三 木 病 院": "三木病院",
                "救 内 小": "救内小",
            }

            for pattern, replacement in patterns.items():
                df1["text"] = df1["text"].str.replace(pattern, replacement, regex=True)

            df1["text"] = (
                df1["text"]
                .str.replace(r"\n(救内小)(\S)", r"\n\1 \2", regex=True)
                .str.replace(r"\n(救(?!内小))(\S)", r"\n\1 \2", regex=True)
                .str.replace(r"\n(内|小|島|歯)(\S)", r"\n\1 \2", regex=True)
                .str.replace(r"(整形外科のみ)\s+", r"整 ", regex=True)
                .str.replace(r"\n歯 .*", "", regex=True)
                .str.replace("~", "～")
                .str.replace(r"\n\(", "(", regex=True)
                .str.replace(r"\n献血\n市民会館前\(10:00～12:00\)", "", regex=True)
            )

            # 日付から始まるもののみ抽出
            df1 = df1.loc[df1["text"].str.match(r"^\d")]

            # １行ごとに分割
            df2 = df1.join(df1["text"].str.split("\n", expand=True)).rename(
                columns={0: "day"}
            )

            # 日付を数値に変換
            df2["day"] = pd.to_numeric(df2["day"], errors="coerce")

            # 不要列を削除
            df2 = (
                df2.dropna(subset="day")
                .astype({"day": int})
                .drop(["row", "text"], axis=1)
            )

            # 病院ごとに整形
            df3 = (
                pd.melt(df2, id_vars=["day", "week"])
                .dropna(subset="value")
                .sort_values(by=["day", "variable"])
                .reset_index(drop=True)
            )

            # "("で病院と時間を分割
            df3[["data", "time"]] = df3["value"].str.split(r"(?<!\))\(", expand=True)

            # 時間を整形
            df3["time"] = df3["time"].str.strip("()").str.replace(")(", " / ")

            # 不要列を削除
            df3.drop("value", axis=1, inplace=True)

            # 分類と病院名を抽出、分類がない場合は""を補完
            df3[["type", "name"]] = df3["data"].apply(
                lambda s: pd.Series(([""] + s.split())[-2:])
            )

            # 分類をリストに変換
            df3["type"] = df3["type"].apply(list)

            # 分類ごとに分割
            df4 = df3.explode("type").copy()

            # kindに変換
            df4["kind"] = (
                df4["type"]
                .map({"救": 1, "整": 4, "内": 5, "小": 7, "島": 9})
                .fillna(1)
                .astype(int)
            )

            # 8:30を08:30に修正
            df4["time"] = df4["time"].str.replace("(?<!0)8:30", "08:30", regex=True)

            # 分類ごとのデフォルト時間を設定

            # 救急
            df4["time"] = df4["time"].mask(
                df4["time"].isna() & (df4["kind"] == 1), "08:30～翌08:30"
            )

            # 整形外科
            df4["time"] = df4["time"].mask(
                df4["time"].isna() & (df4["kind"] == 4), "08:30～17:30"
            )

            # 内科
            df4["time"] = df4["time"].mask(
                df4["time"].isna() & (df4["kind"] == 5), "09:00～17:30"
            )

            # 小児科
            df4["time"] = df4["time"].mask(
                df4["time"].isna() & (df4["kind"] == 7), "09:00～12:00 / 14:00～17:00"
            )

            # 島しょ部
            df4["time"] = df4["time"].mask(
                df4["time"].isna() & (df4["kind"] == 9), "09:00～17:00"
            )

            # 開始日を設定
            start = pd.Timestamp(f"{yyyymm}01")

            # 日から日付に変換
            df4["date"] = df4["day"].apply(lambda d: start.replace(day=d))

            # 曜日を設定
            weeks = list("月火水木金土日")
            df4["week"] = df4["date"].dt.dayofweek.apply(lambda x: weeks[x] + "曜日")

            # 祝日の場合は曜日を"祝日"に変更
            holidays = df4["date"].map(jpholiday.is_holiday)
            df4.loc[holidays, "week"] = "祝日"

            # 診療科目を設定
            df4["medical"] = df4["kind"].map(
                {1: "指定なし", 4: "整形外科", 5: "内科", 7: "小児科", 9: "指定なし"}
            )

            df = df4.reindex(columns=["date", "week", "kind", "medical", "name", "time"])

            df["date"] = df["date"].dt.strftime("%Y-%m-%d")

            # 結果を表示
            st.success("変換が完了しました！")
            st.dataframe(df)

            # CSVファイルとしてダウンロード
            csv = df.to_csv(encoding="utf_8_sig", index=False)
            st.download_button(
                label="CSVファイルをダウンロード",
                data=csv,
                file_name=f"touban_{yyyymm}.csv",
                mime="text/csv",
            )

        except Exception as e:
            st.error(f"エラーが発生しました: {str(e)}")
else:
    st.info("PDFファイルをアップロードしてください")
