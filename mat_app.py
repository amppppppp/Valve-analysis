import calendar
import datetime
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="วิเคราะห์สีและน้ำยา", page_icon="🎨", layout="wide")

PLANTS = ["อยุธยา (AY)", "ขอนแก่น (KK)", "สงขลา (SK)", "นครสวรรค์ (NS)"]
MATERIAL_GROUPS = [
    "สีรองพื้น",
    "สีทับหน้า",
    "ทินเนอร์",
    "สีสกรีน",
    "น้ำยาสกรีน (น้ำมันผสม)",
    "น้ำยา Sealant",
    "ไม่จัดกลุ่ม / ตรวจสอบเอง",
]
MATERIAL_UNITS = {
    "สีรองพื้น": "ถังละ 200 L",
    "สีทับหน้า": "ถังละ 200 L",
    "ทินเนอร์": "ถังละ 200 L",
    "สีสกรีน": "ถังละ 1 kg",
    "น้ำยาสกรีน (น้ำมันผสม)": "ถังละ 25 L",
    "น้ำยา Sealant": "ถังละ 25 L",
    "ไม่จัดกลุ่ม / ตรวจสอบเอง": "ยังไม่กำหนดหน่วย",
}
DEFAULT_LOCAL_DATA_FOLDER = r"D:\PTTOR\ผ.บป.วห - ผ.บป.วห\33-Daily Report และถังทดสอบไม่ซ่อมสี\Stock card"
TRANSFER_KEYWORDS = ["โอน", "ส่งให้", "ส่งไป", "ส่ง", "คป.", "คป", "รซ.", "รซ", "บ้านโรงโป๊ะ", "ลำปาง"]


class LocalDataFile:
    def __init__(self, path):
        self.path = Path(path)
        self.name = self.path.name

    def getvalue(self):
        return self.path.read_bytes()


def normalize_month(value):
    if pd.isna(value):
        return None
    text = str(value).strip().replace(" ", "").replace("..", ".")
    text_without_dot = text[:-1] if text.endswith(".") else text
    try:
        month_number = int(float(text))
        return month_number if 1 <= month_number <= 12 else None
    except ValueError:
        pass
    month_map = {
        "ม.ค": 1, "มค": 1, "ก.พ": 2, "กพ": 2, "มี.ค": 3, "มีค": 3,
        "เม.ย": 4, "เมย": 4, "พ.ค": 5, "พค": 5, "มิ.ย": 6, "มิย": 6,
        "ก.ค": 7, "กค": 7, "ส.ค": 8, "สค": 8, "ก.ย": 9, "กย": 9,
        "ต.ค": 10, "ตค": 10, "พ.ย": 11, "พย": 11, "ธ.ค": 12, "ธค": 12,
    }
    return month_map.get(text_without_dot, month_map.get(text))


def count_workdays_no_sunday(year_ce, month_number):
    try:
        days = calendar.monthrange(int(year_ce), int(month_number))[1]
        return sum(datetime.date(int(year_ce), int(month_number), day).weekday() != 6 for day in range(1, days + 1))
    except (TypeError, ValueError):
        return 26


def auto_detect_plant(file_name):
    upper_name = file_name.upper()
    for code, plant in [("AY", PLANTS[0]), ("KK", PLANTS[1]), ("SK", PLANTS[2]), ("NS", PLANTS[3])]:
        if code in upper_name or plant.split(" (")[0] in file_name:
            return plant
    return PLANTS[0]


def is_transfer(value):
    if pd.isna(value):
        return False
    text = str(value).strip()
    if "ใช้ในโรงงาน" in text or "ใช้ในรง" in text or "สำรองใช้" in text:
        return False
    return any(keyword in text for keyword in TRANSFER_KEYWORDS)


def classify_material(sheet_name):
    """จัดกลุ่มจากชื่อ Sheet เท่านั้น ไม่ใช้ชื่อพัสดุหรือ header มาปน"""
    text = str(sheet_name).lower().replace(" ", "")
    if "สีรองพื้น" in text:
        return "สีรองพื้น"
    if "สีทับหน้า" in text:
        return "สีทับหน้า"
    if "ทินเนอร์" in text or "thinner" in text:
        return "ทินเนอร์"
    if "สีสกรีน" in text:
        return "สีสกรีน"
    if "น้ำยาสกรีน" in text or "น้ำมันผสม" in text:
        return "น้ำยาสกรีน (น้ำมันผสม)"
    if "sealant" in text or "ซีลแลนท์" in text or "ซีแลนท์" in text:
        return "น้ำยา Sealant"
    return "ไม่จัดกลุ่ม / ตรวจสอบเอง"


def find_stock_card_columns(header_frame, column_start):
    if column_start + 8 > header_frame.shape[1]:
        return False
    labels = [str(value).strip() for value in header_frame.iloc[4, column_start:column_start + 8].dropna()]
    has_date = any("วัน" in label for label in labels)
    has_issue = any(any(word in label for word in ["จ่าย", "ใช้", "เบิกเข้า"]) for label in labels)
    has_balance = any("คงเหลือ" in label for label in labels)
    has_receipt = any(any(word in label for word in ["รับ", "จำนวน"]) for label in labels)
    return has_date and has_balance and (has_issue or has_receipt)


@st.cache_data(show_spinner=False)
def scan_workbooks(file_bytes, file_name, plant):
    header_frames = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, header=None, nrows=6)
    found_items = []
    for sheet_name, header_frame in header_frames.items():
        normalized_sheet_name = sheet_name.lower().replace(" ", "")
        if any(keyword in normalized_sheet_name for keyword in ["form", "ยอดคงเหลือ", "สรุปยอดการใช้"]):
            continue
        try:
            for column_start in range(0, min(header_frame.shape[1], 45), 10):
                if not find_stock_card_columns(header_frame, column_start):
                    continue
                item_name = sheet_name
                header_slice = header_frame.iloc[:4, column_start:column_start + 10]
                for row_index in range(header_slice.shape[0]):
                    for column_index in range(header_slice.shape[1] - 1):
                        label = str(header_slice.iloc[row_index, column_index]).strip()
                        if "ชื่อพัสดุ" in label and pd.notna(header_slice.iloc[row_index, column_index + 1]):
                            item_name = str(header_slice.iloc[row_index, column_index + 1]).strip()
                found_items.append({
                    "plant": plant,
                    "file_name": file_name,
                    "sheet_name": sheet_name,
                    "column_start": column_start,
                    "item_name": item_name,
                    "detected_group": classify_material(sheet_name),
                })
        except Exception:
            continue
    return found_items


@st.cache_data(show_spinner=False)
def parse_stock_card(file_bytes, sheet_name, column_start, plant, target_year):
    raw_frame = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, header=4)
    if column_start + 8 > raw_frame.shape[1]:
        return pd.DataFrame()
    data_frame = raw_frame.iloc[:, column_start:column_start + 8].copy()
    data_frame.columns = ["day", "month", "year", "received_from", "received_qty", "issue_to", "issue_qty", "balance"]
    data_frame = data_frame[pd.to_numeric(data_frame["day"], errors="coerce").notna()].copy()
    if data_frame.empty:
        return pd.DataFrame()
    data_frame["day"] = data_frame["day"].astype(int)
    data_frame["month_num"] = data_frame["month"].apply(normalize_month)
    data_frame = data_frame[data_frame["month_num"].notna()].copy()
    data_frame["month_num"] = data_frame["month_num"].astype(int)
    raw_year = pd.to_numeric(data_frame["year"], errors="coerce")
    data_frame["year_be"] = raw_year.apply(lambda value: int(value) if pd.notna(value) and value > 2500 else int(value) + 2500 if pd.notna(value) else np.nan)
    data_frame = data_frame[data_frame["year_be"] == target_year].copy()
    if data_frame.empty:
        return pd.DataFrame()

    data_frame["received_qty"] = pd.to_numeric(data_frame["received_qty"], errors="coerce").fillna(0)
    data_frame["issue_qty"] = pd.to_numeric(data_frame["issue_qty"], errors="coerce").fillna(0)
    data_frame["return_qty"] = 0.0
    if "(NS)" in plant:
        labels = [str(value).strip().lower() for value in raw_frame.iloc[:, column_start:column_start + 8].columns]
        issue_columns = [index for index, label in enumerate(labels) if "เบิกเข้า" in label]
        return_columns = [index for index, label in enumerate(labels) if "คืน" in label]
        if issue_columns:
            data_frame["issue_qty"] = pd.to_numeric(raw_frame.iloc[:, column_start + issue_columns[0]], errors="coerce").fillna(0)
        if return_columns:
            data_frame["return_qty"] = pd.to_numeric(raw_frame.iloc[:, column_start + return_columns[0]], errors="coerce").fillna(0)

    data_frame["balance"] = pd.to_numeric(data_frame["balance"], errors="coerce").ffill()
    data_frame["plant"] = plant
    data_frame["is_transfer"] = data_frame["issue_to"].apply(is_transfer)
    data_frame["transfer_qty"] = np.where(data_frame["is_transfer"], data_frame["issue_qty"], 0.0)
    data_frame["actual_issue_qty"] = np.where(~data_frame["is_transfer"], data_frame["issue_qty"] - data_frame["return_qty"], 0.0)
    return data_frame


def build_export(data_frame):
    monthly = data_frame.groupby(["plant", "material_group", "month_num"], as_index=False).agg(
        received_qty=("received_qty", "sum"), issue_qty=("issue_qty", "sum"),
        return_qty=("return_qty", "sum"), actual_issue_qty=("actual_issue_qty", "sum"),
        transfer_qty=("transfer_qty", "sum"), ending_balance=("balance", "last"),
    )
    target_year = int(data_frame["year_be"].dropna().iloc[0])
    monthly["month_label"] = monthly["month_num"].astype(str) + "/" + str(target_year)
    monthly["unit"] = monthly["material_group"].map(MATERIAL_UNITS).fillna("ยังไม่กำหนดหน่วย")
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        monthly.to_excel(writer, index=False, sheet_name="รายเดือน")
        data_frame.to_excel(writer, index=False, sheet_name="รายการเคลื่อนไหว")
    return output.getvalue()


st.title("🎨 ระบบวิเคราะห์การใช้สีและน้ำยา")
st.caption("AY / KK / SK / NS | สรุปยอดรายเดือนและวางแผนจัดซื้อ โดยยังไม่แปลงหน่วย")
with st.sidebar:
    st.header("ตั้งค่า")
    target_year = st.selectbox("ปี พ.ศ.", [2569, 2568, 2567], index=0)
    exclude_transfers = st.checkbox("ตัดยอดโอนออกจากยอดใช้จริง", value=True)
    lead_time_days = st.number_input("Lead Time (วันทำการ)", min_value=1, max_value=60, value=14)
    safety_days = st.number_input("Safety Stock (วันทำการ)", min_value=0, max_value=90, value=7)
    local_folder = st.text_input("โฟลเดอร์ Excel ที่ Sync", value=DEFAULT_LOCAL_DATA_FOLDER)

uploaded_files = st.file_uploader("อัปโหลด Excel Stock Card", type=["xlsx", "xls"], accept_multiple_files=True)
local_path = Path(local_folder.strip()) if local_folder.strip() else None
local_files = []
if local_path and local_path.is_dir():
    local_files = [LocalDataFile(path) for path in sorted(local_path.glob("*.xlsx"))]
    local_files.extend(LocalDataFile(path) for path in sorted(local_path.glob("*.xls")))
source_files = list(uploaded_files or []) + local_files

if not source_files:
    st.info("อัปโหลดไฟล์ หรือระบุโฟลเดอร์ที่มี Excel Stock Card เพื่อเริ่มใช้งาน")
    st.stop()

file_map = {f"{index}:{file.name}": file for index, file in enumerate(source_files)}
plant_assignments = {}
assignment_columns = st.columns(min(4, len(source_files)))
for index, source_file in enumerate(source_files):
    with assignment_columns[index % len(assignment_columns)]:
        suggestion = auto_detect_plant(source_file.name)
        file_key = f"{index}:{source_file.name}"
        plant_assignments[file_key] = st.selectbox(
            f"พื้นที่: {source_file.name}", PLANTS, index=PLANTS.index(suggestion), key=f"plant_{index}_{source_file.name}"
        )

scanned_items = []
for file_index, source_file in enumerate(source_files):
    file_key = f"{file_index}:{source_file.name}"
    scanned = scan_workbooks(source_file.getvalue(), source_file.name, plant_assignments[file_key])
    for item in scanned:
        item["source_key"] = file_key
    scanned_items.extend(scanned)

if not scanned_items:
    st.error("ไม่พบ Stock Card ตามโครงสร้าง 8 คอลัมน์ที่รองรับ")
    st.stop()

mapping_rows = []
with st.expander("Mapping วัสดุจากชื่อ Sheet / ชื่อพัสดุ", expanded=False):
    with st.form("material_mapping_form"):
        st.caption("ระบบเดาจากชื่อเบื้องต้น รายการที่ไม่แน่ใจให้เลือกใหม่ได้ และจะไม่ถูกเดาเงียบ ๆ")
        for index, item in enumerate(scanned_items):
            columns = st.columns([1.2, 1.5, 2.2, 2.2])
            columns[0].write(item["plant"])
            columns[1].write(item["sheet_name"])
            columns[2].write(item["item_name"])
            default_index = MATERIAL_GROUPS.index(item["detected_group"])
            selected_group = columns[3].selectbox(
                "กลุ่มวัสดุ", MATERIAL_GROUPS, index=default_index, key=f"material_{index}", label_visibility="collapsed"
            )
            if selected_group != "ไม่จัดกลุ่ม / ตรวจสอบเอง":
                mapped_item = item.copy()
                mapped_item["material_group"] = selected_group
                mapping_rows.append(mapped_item)
        st.form_submit_button("บันทึก Mapping และวิเคราะห์")

if not mapping_rows:
    st.warning("ยังไม่มีรายการที่ถูก Mapping")
    st.stop()

entry_frames = []
for item in mapping_rows:
    parsed = parse_stock_card(
        file_map[item["source_key"]].getvalue(),
        item["sheet_name"], item["column_start"], item["plant"], target_year
    )
    if not parsed.empty:
        parsed["material_group"] = item["material_group"]
        parsed["unit"] = MATERIAL_UNITS[item["material_group"]]
        parsed["material_name"] = item["item_name"]
        parsed["source_sheet"] = item["sheet_name"]
        entry_frames.append(parsed)

if not entry_frames:
    st.warning("พบ Mapping แต่ไม่พบรายการของปีที่เลือก")
    st.stop()

all_data = pd.concat(entry_frames, ignore_index=True)
st.success(f"โหลดข้อมูลสำเร็จ {len(all_data):,} รายการ")

monthly = all_data.groupby(["plant", "material_group", "month_num"], as_index=False).agg(
    received_qty=("received_qty", "sum"), issue_qty=("issue_qty", "sum"),
    return_qty=("return_qty", "sum"), actual_issue_qty=("actual_issue_qty", "sum"),
    transfer_qty=("transfer_qty", "sum"), ending_balance=("balance", "last"),
)
monthly["month_label"] = monthly["month_num"].astype(str) + "/" + str(target_year)
monthly["unit"] = monthly["material_group"].map(MATERIAL_UNITS).fillna("ยังไม่กำหนดหน่วย")
monthly["workdays"] = monthly["month_num"].apply(lambda value: count_workdays_no_sunday(target_year - 543, value))
monthly["daily_rate"] = (monthly["actual_issue_qty"] / monthly["workdays"]).round(1)

st.subheader("สรุปยอดรายเดือน")
plant_filter = st.selectbox("พื้นที่", ["รวมทุกพื้นที่"] + PLANTS)
group_filter = st.selectbox("กลุ่มวัสดุ", ["รวมทุกกลุ่ม"] + MATERIAL_GROUPS[:-1])
filtered = monthly.copy()
if plant_filter != "รวมทุกพื้นที่":
    filtered = filtered[filtered["plant"] == plant_filter]
if group_filter != "รวมทุกกลุ่ม":
    filtered = filtered[filtered["material_group"] == group_filter]
summary_tab, plant_chart_tab = st.tabs(["ตารางสรุป", "กราฟแยกโรงงาน"])
with summary_tab:
    st.caption("หน่วย: สีรองพื้น/สีทับหน้า/ทินเนอร์ = ถังละ 200 L | สีสกรีน = ถังละ 1 kg | น้ำยาสกรีน (น้ำมันผสม)/น้ำยา Sealant = ถังละ 25 L")
    st.dataframe(filtered, use_container_width=True)
    chart = filtered.groupby("month_label", as_index=False)["actual_issue_qty"].sum()
    if not chart.empty:
        st.plotly_chart(
            px.bar(chart, x="month_label", y="actual_issue_qty", title="ยอดใช้จริงรายเดือน"),
            use_container_width=True,
        )

with plant_chart_tab:
    chart_plant = st.selectbox("เลือกโรงงานสำหรับกราฟ", ["รวมทุกโรงงาน"] + PLANTS, key="material_chart_plant")
    chart_group = st.selectbox("เลือกกลุ่มสำหรับกราฟ", ["รวมทุกกลุ่ม"] + MATERIAL_GROUPS[:-1], key="material_chart_group")
    chart_source = monthly.copy()
    if chart_plant != "รวมทุกโรงงาน":
        chart_source = chart_source[chart_source["plant"] == chart_plant]
    if chart_group != "รวมทุกกลุ่ม":
        chart_source = chart_source[chart_source["material_group"] == chart_group]
    plant_chart = chart_source.groupby(
        ["month_label", "plant"], as_index=False
    )["actual_issue_qty"].sum()
    if not plant_chart.empty:
        st.plotly_chart(
            px.bar(
                plant_chart,
                x="month_label",
                y="actual_issue_qty",
                color="plant",
                barmode="group",
                title="ยอดใช้จริงแยกโรงงาน",
            ),
            use_container_width=True,
        )
        st.dataframe(plant_chart, use_container_width=True)

st.subheader("แผนจัดซื้อเบื้องต้น")
latest = all_data.sort_values(["plant", "material_group", "month_num"]).groupby(["plant", "material_group"], as_index=False).tail(1).copy()
latest["unit"] = latest["material_group"].map(MATERIAL_UNITS).fillna("ยังไม่กำหนดหน่วย")
latest["workdays"] = latest["month_num"].apply(lambda value: count_workdays_no_sunday(target_year - 543, value))
rate_basis = monthly.groupby(["plant", "material_group"], as_index=False).tail(3).groupby(["plant", "material_group"], as_index=False)["daily_rate"].mean()
plan = latest[["plant", "material_group", "unit", "balance", "month_num"]].rename(columns={"balance": "current_stock"}).merge(rate_basis, on=["plant", "material_group"])
plan["safety_stock"] = (plan["daily_rate"] * safety_days).round()
plan["rop"] = (plan["daily_rate"] * lead_time_days + plan["safety_stock"]).round()
plan["status"] = np.where(plan["current_stock"] <= plan["rop"], "ควรพิจารณาสั่งซื้อ", "เพียงพอ")
st.dataframe(plan, use_container_width=True)

st.subheader("Export")
st.download_button("📥 ดาวน์โหลด Excel", data=build_export(all_data), file_name=f"material_analysis_{target_year}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
