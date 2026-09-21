import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import calendar
import datetime
import io
import re
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import urlopen

st.set_page_config(
    page_title="ระบบวิเคราะห์และจำลองการจัดซื้อวาล์ว",
    page_icon="📦",
    layout="wide"
)

st.title("📦 ระบบวิเคราะห์การใช้วาล์ว & จำลองแผนจัดซื้อล่วงหน้า (Simulation)")
st.caption("ระบบตรวจจับ 'การโอนระหว่างคลัง' แยกจากการใช้จริงอัตโนมัติ และรองรับตัวเลือก 'รวมวาล์วทุกประเภท'")

# --- พจนานุกรมรหัสพัสดุมาตรฐาน (Master Code Registry) --- #
CODE_TO_VALVE = {
    '900316': 'วาล์วมือหมุน 15 กก.',
    '900196': 'วาล์วมือหมุน 48 กก.',
    '900010': 'วาล์วมือหมุน 4/7 กก.',
    '900013': 'วาล์วแค้มปิ้ง',
    '900014': 'FL - วาล์วบรรจุ 15 กก. FL',
    '900015': 'FL - วาล์วจ่าย 15 กก. FL',
    '900007': 'FL - วาล์วนิรภัย 15 กก. FL',
    '900005': 'FL - เกจวัดแรงดัน 15 กก. FL',
    '900016': 'LW - วาล์วบรรจุ 48 กก. L/W',
    '900017': 'LW - วาล์วจ่าย 48 กก. L/W',
}

STANDARD_VALVE_TYPES = list(CODE_TO_VALVE.values()) + ["วาล์วเปิด-ปิด", "วาล์วชำรุด", "อื่นๆ / ข้ามรายการนี้"]
BP_VALVE_TYPES = [
    "วาล์ว 4 กก. Valve ใหม่", "วาล์ว 7 กก. Valve ใหม่", "วาล์ว 15 กก. Valve ใหม่",
    "วาล์ว 15 กก. FL บรรจุ", "วาล์ว 15 กก. FL จ่าย",
    "วาล์ว 15 กก. FL เกจวัด", "วาล์ว 15 กก. FL นิรภัย",
    "วาล์ว 48 กก. Valve ใหม่", "วาล์ว 48 กก. LW บรรจุ",
    "วาล์ว 48 กก. LW จ่าย"
]
STANDARD_VALVE_TYPES = list(dict.fromkeys(STANDARD_VALVE_TYPES + BP_VALVE_TYPES))
ALL_VALVES_LABEL = "📦 รวมวาล์วทุกประเภท (All Valve Types Combined)"
PLANT_OPTIONS = ["อยุธยา (AY)", "ขอนแก่น (KK)", "สงขลา (SK)", "นครสวรรค์ (NS)", "บ้านโรงโป๊ะ (BP)", "อื่นๆ (ระบุเอง)"]

MONTH_TH_NAMES = {
    1: 'ม.ค.', 2: 'ก.พ.', 3: 'มี.ค.', 4: 'เม.ย.', 5: 'พ.ค.', 6: 'มิ.ย.',
    7: 'ก.ค.', 8: 'ส.ค.', 9: 'ก.ย.', 10: 'ต.ค.', 11: 'พ.ย.', 12: 'ธ.ค.'
}

# คำสำคัญสำหรับตรวจจับการโอนไประหว่างคลัง/โรงซ่อมอื่น
TRANSFER_KEYWORDS = [
    'โอน', 'ส่งให้', 'ส่งไป', 'ส่ง', 'คป.', 'คป', 'รซ.', 'รซ',
    'ชื่นศิริ', 'ชื่น', 'เมทเทิลเมท', 'เมท', 'สหมิตร', 'ลำปาง', 'บ้านโรงโป๊ะ', 'นว.'
]

DEFAULT_LOCAL_DATA_FOLDER = r"D:\PTTOR\ผ.บป.วห - ผ.บป.วห\45-วาล์วสำหรับถังซ่อม\1. ไฟล์ที่จำเป็นสำหรับการงานจัดซื้อวาล์ว\Valve stock analysis"

class LocalDataFile:
    def __init__(self, path):
        self.path = Path(path)
        self.name = self.path.name

    def getvalue(self):
        return self.path.read_bytes()

def is_transfer_issue(issue_to_val):
    """ตรวจจับว่ารายการจ่ายนี้เป็นการโอนไปคลัง/โรงงานอื่นหรือไม่"""
    if pd.isna(issue_to_val):
        return False
    s = str(issue_to_val).strip()
    if 'ใช้ในรง' in s or 'ใช้ในโรงงาน' in s or 'สำรองใช้' in s:
        return False
    for kw in TRANSFER_KEYWORDS:
        if kw in s:
            return True
    return False

def normalize_month(val):
    if pd.isna(val):
        return None
    s = str(val).strip().replace(' ', '').replace('..', '.')
    s_nodot = s[:-1] if s.endswith('.') else s
    try:
        f = float(s)
        if 1 <= f <= 12:
            return int(f)
    except ValueError:
        pass
    mapping = {
        'ม.ค': 1, 'มค': 1, 'ก.พ': 2, 'กพ': 2, 'มี.ค': 3, 'มีค': 3,
        'เม.ย': 4, 'เมย': 4, 'พ.ค': 5, 'พค': 5, 'มิ.ย': 6, 'มิย': 6,
        'ก.ค': 7, 'กค': 7, 'ส.ค': 8, 'สค': 8, 'ก.ย': 9, 'กย': 9,
        'ต.ค': 10, 'ตค': 10, 'พ.ย': 11, 'พย': 11, 'ธ.ค': 12, 'ธค': 12
    }
    return mapping.get(s_nodot, mapping.get(s, None))

def count_workdays_no_sunday(year_ce, month):
    try:
        if pd.isna(year_ce) or pd.isna(month):
            return 26
        y = int(round(float(year_ce)))
        m = int(round(float(month)))
        if m < 1 or m > 12:
            return 26
        days_in_month = calendar.monthrange(y, m)[1]
        return sum(1 for d in range(1, days_in_month + 1) if datetime.date(y, m, d).weekday() != 6)
    except Exception:
        return 26

def auto_detect_plant(filename):
    name = filename.upper()
    if "AY" in name or "อยุธยา" in name:
        return "อยุธยา (AY)"
    elif "KK" in name or "ขอนแก่น" in name:
        return "ขอนแก่น (KK)"
    elif "SK" in name or "สงขลา" in name:
        return "สงขลา (SK)"
    elif "NS" in name or "นครสวรรค์" in name:
        return "นครสวรรค์ (NS)"
    elif "BP" in name or "บ้านโรงโป๊ะ" in name:
        return "บ้านโรงโป๊ะ (BP)"
    return "อยุธยา (AY)"

def is_valid_stock_card_col(df_raw, c):
    """ตรวจสอบว่าช่วงคอลัมน์นี้เป็นตาราง Stock Card 8 คอลัมน์ที่สมบูรณ์หรือไม่"""
    if c + 8 > df_raw.shape[1]:
        return False
    if len(df_raw) <= 4:
        return False
    row4 = [str(x).strip() for x in df_raw.iloc[4, c:c+8].dropna()]
    has_date = any('วัน' in x for x in row4)
    has_issue = any('จ่าย' in x or 'ใช้' in x or 'เบิกเข้า' in x for x in row4)
    has_bal = any('คงเหลือ' in x for x in row4)
    has_rcv = any('รับ' in x or 'จำนวน' in x for x in row4)
    return has_date and has_bal and (has_issue or has_rcv)

def clean_guess(sheet, item_name, item_code):
    """เดาชนิดวาล์วอย่างแม่นยำ พร้อมคัดกรองชิ้นส่วนที่ไม่ใช่วาล์วออก"""
    if item_code in CODE_TO_VALVE:
        return CODE_TO_VALVE[item_code]
    
    non_valves = ['ฐาน', 'หู', 'สี', 'ทินเนอร์', 'ลวด', 'พลาสม่า', 'ฟิลเตอร์', 'น้ำยา', 'กระดาษ', 'เทป', 'สติ๊กเกอร์', 'คาร์บอน', 'Carbon', 'เม็ดเหล็ก', 'tag', 'CO2']
    if any(nv in sheet for nv in non_valves) and not ('วาล์ว' in sheet or 'V' in sheet):
        return 'อื่นๆ / ข้ามรายการนี้'
    if any(nv in str(item_name) for nv in ['ฐานถัง', 'หูถัง']):
        return 'อื่นๆ / ข้ามรายการนี้'
        
    s_clean = sheet.strip()
    if 'ชำรุด' in s_clean or (item_name and 'ชำรุด' in str(item_name)):
        return 'วาล์วชำรุด'
    if 'เปิด-ปิด' in s_clean or (item_name and ('เปิด-ปิด' in str(item_name) or 'เปิด - ปิด' in str(item_name))):
        return 'วาล์วเปิด-ปิด'
    if 'แค้ม' in s_clean or (item_name and 'แค้ม' in str(item_name)):
        return 'วาล์วแค้มปิ้ง'
    if '4_7' in s_clean or (item_name and '4/7' in str(item_name)):
        return 'วาล์วมือหมุน 4/7 กก.'
    if '15-48' in s_clean or (item_name and '15/48' in str(item_name)) or ('48' in s_clean and 'LW' not in s_clean):
        return 'วาล์วมือหมุน 48 กก.'
    if '15' in s_clean and 'FL' not in s_clean and 'ฐาน' not in s_clean and 'หู' not in s_clean:
        return 'วาล์วมือหมุน 15 กก.'
        
    return 'อื่นๆ / ข้ามรายการนี้'

@st.cache_data(show_spinner=False)
def _scan_all_sheets_and_codes_cached(file_bytes, file_name, loc_name):
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    found_items = []
    
    for sheet in xls.sheet_names:
        if 'Form' in sheet:
            continue
        try:
            df_head = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet, header=None, nrows=6)
            for c in range(0, min(df_head.shape[1], 45), 10):
                if is_valid_stock_card_col(df_head, c):
                    sub = df_head.iloc[:4, c:min(c+10, df_head.shape[1])]
                    item_code = None
                    item_name = None
                    for r in range(len(sub)):
                        for col_idx in range(sub.shape[1]):
                            val = str(sub.iloc[r, col_idx]).strip()
                            if 'รหัส' in val and col_idx + 1 < sub.shape[1]:
                                raw_code = sub.iloc[r, col_idx+1]
                                if pd.notna(raw_code):
                                    try:
                                        item_code = str(int(float(raw_code)))
                                    except:
                                        item_code = str(raw_code).strip()
                            if 'ชื่อพัสดุ' in val and col_idx + 1 < sub.shape[1]:
                                item_name = str(sub.iloc[r, col_idx+1:col_idx+4].dropna().values[0]).strip() if len(sub.iloc[r, col_idx+1:col_idx+4].dropna()) > 0 else ""
                    
                    guessed_type = clean_guess(sheet, item_name, item_code)
                    
                    if guessed_type != 'อื่นๆ / ข้ามรายการนี้' or (item_name and 'วาล์ว' in item_name):
                        found_items.append({
                            'location': loc_name,
                            'file_name': file_name,
                            'sheet_name': sheet,
                            'col_start': c,
                            'item_code': item_code if item_code else "-",
                            'raw_item_name': item_name if item_name else sheet,
                            'detected_type': guessed_type
                        })
        except Exception:
            pass
    return found_items

def scan_all_sheets_and_codes(uploaded_file, loc_name):
    return _scan_all_sheets_and_codes_cached(uploaded_file.getvalue(), uploaded_file.name, loc_name)

@st.cache_data(show_spinner=False)
def _parse_valve_data_cached(file_bytes, sheet_name, col_start, location_name, target_year_be=2569):
    raw_df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, header=4)
    if col_start + 8 > raw_df.shape[1]:
        return pd.DataFrame()
        
    df = raw_df.iloc[:, col_start:col_start+8].copy()
    df.columns = ['day', 'month', 'year', 'rcv_from', 'rcv_qty', 'issue_to', 'issue_qty', 'balance']
    df = df[pd.to_numeric(df['day'], errors='coerce').notna()].copy()
    if len(df) == 0:
        return pd.DataFrame()
        
    df['day'] = df['day'].astype(int)
    df['month_num'] = df['month'].apply(normalize_month)
    df = df[df['month_num'].notna()].copy()
    df['month_num'] = df['month_num'].astype(int)
    df['year_raw'] = pd.to_numeric(df['year'], errors='coerce')
    df['year_be'] = df['year_raw'].apply(lambda y: int(y) if y > 2500 else int(y) + 2500 if pd.notna(y) else np.nan)
    df = df[df['year_be'] == target_year_be].copy()
    if len(df) == 0:
        return pd.DataFrame()
        
    df['rcv_qty'] = pd.to_numeric(df['rcv_qty'], errors='coerce').fillna(0)
    df['issue_qty'] = pd.to_numeric(df['issue_qty'], errors='coerce').fillna(0)
    df['return_qty'] = 0.0

    # นครสวรรค์บันทึก "เบิกเข้า" และ "คืน" แยกคอลัมน์ จึงคิดยอดใช้จริงเป็น เบิกเข้า - คืน
    if 'นครสวรรค์' in location_name or '(NS)' in location_name:
        header_names = [str(value).strip().lower() for value in raw_df.iloc[:, col_start:col_start+8].columns]
        issue_columns = [index for index, name in enumerate(header_names) if 'เบิกเข้า' in name]
        return_columns = [index for index, name in enumerate(header_names) if 'คืน' in name]
        if issue_columns:
            df['issue_qty'] = pd.to_numeric(
                raw_df.iloc[:, col_start + issue_columns[0]], errors='coerce'
            ).fillna(0)
        if return_columns:
            df['return_qty'] = pd.to_numeric(
                raw_df.iloc[:, col_start + return_columns[0]], errors='coerce'
            ).fillna(0)
    df['balance'] = pd.to_numeric(df['balance'], errors='coerce').ffill()
    df['location'] = location_name
    
    # แยกประเภทการจ่าย: โอนออก vs ใช้จริง
    df['is_transfer'] = df['issue_to'].apply(is_transfer_issue)
    df['transfer_qty'] = np.where(df['is_transfer'], df['issue_qty'], 0.0)
    df['actual_issue_qty'] = np.where(
        ~df['is_transfer'], df['issue_qty'] - df['return_qty'], 0.0
    )
    
    return df

def parse_valve_data(uploaded_file, sheet_name, col_start, location_name, target_year_be=2569):
    return _parse_valve_data_cached(
        uploaded_file.getvalue(), sheet_name, col_start, location_name, target_year_be
    )

@st.cache_data(show_spinner=False)
def load_bp_google_sheet(sheet_url, target_year_be):
    """อ่านแท็บยอดใช้วาล์วใหม่จาก Google Sheet ที่เปิดให้เข้าถึงได้"""
    try:
        sheet_id = sheet_url.split('/spreadsheets/d/')[1].split('/')[0]
        query = parse_qs(urlparse(sheet_url).query)
        gid = query.get('gid', [None])[0]
        if gid:
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={quote(gid)}"
        else:
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&sheet={quote('ยอดใช้วาล์วใหม่')}"
        with urlopen(csv_url, timeout=20) as response:
            raw = response.read()
        source = pd.read_csv(io.BytesIO(raw), header=None, encoding='utf-8')
        # รูปแบบ BP เป็นตารางไขว้: วันที่อยู่แถว และขนาดวาล์วอยู่คอลัมน์
        if source.shape[0] > 4 and source.shape[1] >= 11:
            # คอลัมน์ BP ตามหัวตารางจริง: 4 kg, 7 kg, 15 kg, FL 4 รายการ,
            # 48 kg และ LW 2 รายการ ตามลำดับ
            valve_groups = dict(zip(range(1, 11), BP_VALVE_TYPES))
            month_pattern = '|'.join(MONTH_TH_NAMES.values())
            rows = []
            for row_index in range(4, len(source)):
                date_text = str(source.iloc[row_index, 0]).strip()
                match = re.match(r'^(\d{1,2})\s*(' + month_pattern + r')', date_text)
                if not match:
                    continue
                day = int(match.group(1))
                month_num = normalize_month(match.group(2))
                for column_index, valve_type in valve_groups.items():
                    quantity = pd.to_numeric(source.iloc[row_index, column_index], errors='coerce')
                    if pd.isna(quantity):
                        quantity = 0.0
                    rows.append({
                        'valve_type': valve_type, 'day': day, 'month_num': month_num,
                        'year_be': target_year_be, 'issue_qty': float(quantity),
                        'rcv_from': '', 'rcv_qty': 0.0,
                        'issue_to': 'ใช้จริงจาก Google Sheet', 'balance': np.nan,
                        'location': 'บ้านโรงโป๊ะ (BP)', 'is_transfer': False,
                        'transfer_qty': 0.0, 'return_qty': 0.0,
                        'actual_issue_qty': float(quantity)
                    })
            return pd.DataFrame(rows)

        source = source.iloc[1:].copy()
        source.columns = [str(column).strip() for column in source.columns]
        names = {column: column.lower().replace(' ', '') for column in source.columns}

        def find_column(words, excluded=()):
            for column, normalized in names.items():
                if any(word in normalized for word in words) and not any(word in normalized for word in excluded):
                    return column
            return None

        valve_column = find_column(['ชนิดวาล์ว', 'ประเภทวาล์ว', 'ขนาดวาล์ว', 'ชื่อวาล์ว', 'วาล์ว', 'valve'])
        quantity_column = find_column(['ยอดใช้', 'จำนวนใช้', 'ใช้วาล์ว', 'เบิกใช้', 'usage', 'quantity', 'qty'], ['คงเหลือ'])
        date_column = find_column(['วันที่', 'date'])
        month_column = find_column(['เดือน', 'month'])
        year_column = find_column(['ปี', 'year'])
        day_column = find_column(['วัน', 'day']) if not date_column else None
        if not valve_column or not quantity_column or not (date_column or (month_column and year_column)):
            return pd.DataFrame()

        result = pd.DataFrame()
        result['valve_type'] = source[valve_column].astype(str).str.strip()
        result['issue_qty'] = pd.to_numeric(source[quantity_column], errors='coerce').fillna(0)
        if date_column:
            dates = pd.to_datetime(source[date_column], errors='coerce', dayfirst=True)
            result['day'] = dates.dt.day
            result['month_num'] = dates.dt.month
            result['year_be'] = dates.dt.year + 543
        else:
            result['day'] = pd.to_numeric(source[day_column], errors='coerce') if day_column else 1
            result['month_num'] = source[month_column].apply(normalize_month)
            raw_year = pd.to_numeric(source[year_column], errors='coerce')
            result['year_be'] = raw_year.apply(lambda year: int(year) if year > 2500 else int(year) + 543 if pd.notna(year) else np.nan)

        result = result[result['year_be'] == target_year_be].copy()
        result = result[result['valve_type'].notna() & (result['valve_type'] != 'nan')]
        result['day'] = pd.to_numeric(result['day'], errors='coerce').fillna(1).astype(int)
        result['month_num'] = pd.to_numeric(result['month_num'], errors='coerce')
        result['rcv_from'] = ''
        result['rcv_qty'] = 0.0
        result['issue_to'] = 'ใช้จริงจาก Google Sheet'
        result['balance'] = np.nan
        result['location'] = 'บ้านโรงโป๊ะ (BP)'
        result['is_transfer'] = False
        result['transfer_qty'] = 0.0
        result['return_qty'] = 0.0
        result['actual_issue_qty'] = result['issue_qty']
        return result.dropna(subset=['month_num'])
    except Exception:
        return pd.DataFrame()

@st.cache_data(show_spinner=False)
def load_all_mapped_data(entry_specs, target_year_be, bp_data):
    """รวมข้อมูลที่ mapping แล้วครั้งเดียว ใช้ร่วมกันทุกแท็บในรอบการทำงาน"""
    parsed_frames = []
    for source, file_bytes, sheet_name, col_start, location, valve_type in entry_specs:
        if source == 'google':
            parsed = bp_data[bp_data['valve_type'] == valve_type].copy()
        else:
            parsed = _parse_valve_data_cached(
                file_bytes, sheet_name, col_start, location, target_year_be
            )
        if len(parsed) > 0:
            parsed['valve_type'] = valve_type
            parsed_frames.append(parsed)
    return pd.concat(parsed_frames, ignore_index=True) if parsed_frames else pd.DataFrame()

@st.cache_data(show_spinner=False)
def build_export_excel(df_all):
    """สร้างไฟล์ Excel รายงานแยกพื้นที่ แยกชนิดวาล์ว และอัตราการใช้ย้อนหลัง"""
    export_df = df_all.copy()
    target_year_be = int(export_df['year_be'].dropna().iloc[0])

    monthly = export_df.groupby(['location', 'valve_type', 'month_num'], as_index=False).agg(
        ยอดรับเข้า=('rcv_qty', 'sum'),
        เบิกใช้จริง=('actual_issue_qty', 'sum'),
        คืน=('return_qty', 'sum'),
        โอนออก=('transfer_qty', 'sum'),
        จ่ายรวม=('issue_qty', 'sum'),
        คงเหลือสิ้นเดือน=('balance', 'last')
    )
    monthly['ปี พ.ศ.'] = target_year_be
    monthly['วันทำงาน'] = monthly['month_num'].apply(
        lambda month: count_workdays_no_sunday(target_year_be - 543, month)
    ).astype(int)
    monthly['อัตราใช้จริง (ตัว/วัน)'] = (monthly['เบิกใช้จริง'] / monthly['วันทำงาน']).round(1)
    monthly['อัตราจ่ายรวม (ตัว/วัน)'] = (monthly['จ่ายรวม'] / monthly['วันทำงาน']).round(1)
    monthly['เดือน'] = monthly['month_num'].astype(str) + '/' + monthly['ปี พ.ศ.'].astype(str)
    monthly = monthly[['location', 'valve_type', 'เดือน', 'month_num', 'ปี พ.ศ.', 'ยอดรับเข้า', 'เบิกใช้จริง', 'คืน', 'โอนออก', 'จ่ายรวม', 'คงเหลือสิ้นเดือน', 'วันทำงาน', 'อัตราใช้จริง (ตัว/วัน)', 'อัตราจ่ายรวม (ตัว/วัน)']]

    area_summary = monthly.groupby(['location', 'เดือน', 'month_num', 'ปี พ.ศ.'], as_index=False).agg(
        ยอดรับเข้ารวม=('ยอดรับเข้า', 'sum'), เบิกใช้จริงรวม=('เบิกใช้จริง', 'sum'), คืนรวม=('คืน', 'sum'),
        โอนออกรวม=('โอนออก', 'sum'), จ่ายรวม=('จ่ายรวม', 'sum'),
        คงเหลือรวม=('คงเหลือสิ้นเดือน', 'sum')
    )
    workdays = monthly[['เดือน', 'month_num', 'ปี พ.ศ.', 'วันทำงาน']].drop_duplicates()
    area_summary = area_summary.merge(workdays, on=['เดือน', 'month_num', 'ปี พ.ศ.'], how='left')
    area_summary['อัตราใช้จริงรวม (ตัว/วัน)'] = (area_summary['เบิกใช้จริงรวม'] / area_summary['วันทำงาน']).round(1)

    valve_summary = monthly.groupby(['valve_type', 'เดือน', 'month_num', 'ปี พ.ศ.'], as_index=False).agg(
        ยอดรับเข้ารวม=('ยอดรับเข้า', 'sum'), เบิกใช้จริงรวม=('เบิกใช้จริง', 'sum'), คืนรวม=('คืน', 'sum'),
        โอนออกรวม=('โอนออก', 'sum'), จ่ายรวม=('จ่ายรวม', 'sum'),
        คงเหลือรวม=('คงเหลือสิ้นเดือน', 'sum')
    )
    valve_summary = valve_summary.merge(workdays, on=['เดือน', 'month_num', 'ปี พ.ศ.'], how='left')
    valve_summary['อัตราใช้จริงรวม (ตัว/วัน)'] = (valve_summary['เบิกใช้จริงรวม'] / valve_summary['วันทำงาน']).round(1)

    transactions = export_df.rename(columns={
        'location': 'พื้นที่', 'valve_type': 'ชนิดวาล์ว', 'day': 'วันที่', 'month_num': 'เดือนที่',
        'year_be': 'ปี พ.ศ.', 'rcv_from': 'รับจาก', 'rcv_qty': 'ยอดรับเข้า', 'issue_to': 'จ่ายให้',
        'issue_qty': 'ยอดจ่าย', 'actual_issue_qty': 'เบิกใช้จริง', 'transfer_qty': 'โอนออก',
        'return_qty': 'คืน', 'balance': 'คงเหลือ', 'is_transfer': 'เป็นรายการโอน'
    })
    detail_columns = ['พื้นที่', 'ชนิดวาล์ว', 'วันที่', 'เดือนที่', 'ปี พ.ศ.', 'รับจาก', 'ยอดรับเข้า', 'จ่ายให้', 'ยอดจ่าย', 'เบิกใช้จริง', 'คืน', 'โอนออก', 'คงเหลือ', 'เป็นรายการโอน']
    transactions = transactions[detail_columns]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        monthly.to_excel(writer, index=False, sheet_name='รายเดือน_พื้นที่_วาล์ว')
        area_summary.to_excel(writer, index=False, sheet_name='สรุปแยกพื้นที่')
        valve_summary.to_excel(writer, index=False, sheet_name='สรุปแยกขนาดวาล์ว')
        transactions.to_excel(writer, index=False, sheet_name='รายการเคลื่อนไหว')
    output.seek(0)
    return output.getvalue()

# --- Sidebar Controls --- #
with st.sidebar:
    st.header("⚙️ ตั้งค่าทั่วไป")
    target_year = st.selectbox("ปีที่ต้องการวิเคราะห์ (พ.ศ.):", [2569, 2568, 2567], index=0)
    
    st.markdown("---")
    st.header("🔍 การกรองยอดโอนระหว่างคลัง")
    exclude_transfers = st.checkbox(
        "ตัดยอดโอนออก (ไม่นำมาคิดเป็นอัตราการใช้จริง)",
        value=True,
        help="หากติ๊กเลือก: อัตราการใช้ต่อวัน (Burn Rate) จะคำนวณจาก 'การเบิกใช้จริงในโรงงาน' เท่านั้น เพื่อไม่ให้ยอดโอนก้อนใหญ่ทำให้ค่าเฉลี่ยเพี้ยน"
    )
    
    st.markdown("---")
    st.header("📦 พารามิเตอร์การจัดซื้อ")
    lead_time_days = st.number_input("Lead Time จัดซื้อ (วันทำการ):", min_value=1, max_value=60, value=14)
    safety_stock_days = st.number_input("Safety Stock สำรอง (วันทำการ):", min_value=0, max_value=45, value=7)
    order_cycle_days = st.number_input("รอบการจัดซื้อถัดไป (วันทำการ):", min_value=7, max_value=90, value=30)

# --- Upload Files --- #
st.subheader("1. อัปโหลดไฟล์ Stock Card")
uploaded_files = st.file_uploader(
    "เลือกไฟล์ Excel ของคลังที่ต้องการวิเคราะห์ (อัปโหลดพร้อมกันได้หลายไฟล์):",
    type=["xlsx", "xls"],
    accept_multiple_files=True
)
local_data_folder = st.text_input(
    "หรืออ่านไฟล์จากโฟลเดอร์ SharePoint/OneDrive ในเครื่อง:",
    value=DEFAULT_LOCAL_DATA_FOLDER,
    help="ต้องเป็นโฟลเดอร์ที่ Sync ไว้ในเครื่องนี้ และควรมีไฟล์ .xlsx หรือ .xls อยู่ภายใน"
)
local_files = []
local_path = Path(local_data_folder.strip()) if local_data_folder.strip() else None
if local_path and local_path.is_dir():
    local_files = [LocalDataFile(path) for path in sorted(local_path.glob("*.xlsx"))]
    local_files.extend(LocalDataFile(path) for path in sorted(local_path.glob("*.xls")))
    if local_files:
        st.success(f"พบไฟล์จากโฟลเดอร์ในเครื่อง {len(local_files)} ไฟล์")
    else:
        st.info("พบโฟลเดอร์แล้ว แต่ยังไม่มีไฟล์ Excel")
elif local_data_folder.strip():
    st.warning("ไม่พบโฟลเดอร์ Location นี้ในเครื่อง")

source_files = list(uploaded_files or [])
source_files.extend(local_files)
bp_google_url = st.text_input(
    "Google Sheet บ้านโรงโป๊ะ (BP) - URL (ไม่บังคับ):",
    value="https://docs.google.com/spreadsheets/d/1rSx6ivg3kaO-FEHAMP2IWJAy4Pb9A8t3TZ5i3qNKT18/edit?usp=sharing",
    help="ระบบจะอ่านแท็บ 'ยอดใช้วาล์วใหม่' โดยตรง ต้องเปิดสิทธิ์ให้ผู้ที่มีลิงก์ดูได้"
)
if st.button("🔄 ดึงข้อมูล BP ใหม่", help="ล้าง cache แล้วอ่าน Google Sheet ล่าสุด"):
    load_bp_google_sheet.clear()
    st.rerun()

if source_files:
    file_map = {f.name: f for f in source_files}
    st.write("📍 **กำหนดพื้นที่ (Plant) ของแต่ละไฟล์:**")
    plant_assignments = {}
    cols = st.columns(min(len(source_files), 3))
    for idx, f in enumerate(source_files):
        col = cols[idx % len(cols)]
        with col:
            sugg = auto_detect_plant(f.name)
            default_p_idx = PLANT_OPTIONS.index(sugg) if sugg in PLANT_OPTIONS else 0
            chosen = st.selectbox(f"ไฟล์: {f.name}", PLANT_OPTIONS, index=default_p_idx, key=f"pl_{f.name}")
            plant_assignments[f.name] = chosen

    # สแกนหาชีตและรหัสพัสดุ
    all_scanned_items = []
    for f in source_files:
        items = scan_all_sheets_and_codes(f, plant_assignments[f.name])
        all_scanned_items.extend(items)

    # --- Manual Mapping Expander --- #
    mapping_results = []
    with st.expander("🛠️ ตรวจสอบ / แก้ไขการจับคู่ประเภทวาล์ว (Valve Mapping UI)", expanded=False):
        st.info("💡 ระบบจับคู่อัตโนมัติจาก 'รหัสพัสดุ' ให้แล้ว หากต้องการเปลี่ยนคู่ สามารถเลือกใน Dropdown:")
        m_cols = st.columns([2, 2, 2, 2, 3])
        m_cols[0].write("**พื้นที่**")
        m_cols[1].write("**ชื่อ Sheet**")
        m_cols[2].write("**รหัสพัสดุที่พบ**")
        m_cols[3].write("**ชื่อเดิมในไฟล์**")
        m_cols[4].write("**กำหนดเป็นวาล์วประเภท (Mapped To):**")

        for i, item in enumerate(all_scanned_items):
            c0, c1, c2, c3, c4 = st.columns([2, 2, 2, 2, 3])
            c0.write(f"📍 {item['location']}")
            c1.write(f"`{item['sheet_name']}` (col {item['col_start']})")
            c2.write(f"**{item['item_code']}**")
            c3.write(item['raw_item_name'])
            
            default_choice_idx = STANDARD_VALVE_TYPES.index(item['detected_type']) if item['detected_type'] in STANDARD_VALVE_TYPES else 0
            user_selected_type = c4.selectbox(
                f"map_{i}",
                STANDARD_VALVE_TYPES,
                index=default_choice_idx,
                key=f"user_map_{i}",
                label_visibility="collapsed"
            )
            if user_selected_type != "อื่นๆ / ข้ามรายการนี้":
                item_copy = item.copy()
                item_copy['final_mapped_type'] = user_selected_type
                mapping_results.append(item_copy)

    bp_data = load_bp_google_sheet(bp_google_url, target_year) if bp_google_url.strip() else pd.DataFrame()
    if bp_google_url.strip():
        if len(bp_data) > 0:
            st.success(f"โหลดข้อมูล BP สำเร็จ {len(bp_data):,} รายการ จากแท็บยอดใช้วาล์วใหม่")
        else:
            st.error("โหลดข้อมูล BP ไม่สำเร็จ กรุณาตรวจสิทธิ์ Anyone with the link หรือ URL Google Sheet")
    if len(bp_data) > 0:
        for valve_name in sorted(bp_data['valve_type'].unique()):
            mapping_results.append({
                'location': 'บ้านโรงโป๊ะ (BP)',
                'file_name': '__bp_google_sheet__',
                'sheet_name': 'ยอดใช้วาล์วใหม่',
                'col_start': 0,
                'item_code': '-',
                'raw_item_name': valve_name,
                'detected_type': valve_name,
                'final_mapped_type': valve_name,
                'source': 'google'
            })

    if mapping_results:
        df_mapped = pd.DataFrame(mapping_results)

        entry_specs = tuple(
            (
                entry.get('source', 'excel'),
                b'' if entry.get('source') == 'google' else file_map[entry['file_name']].getvalue(),
                entry['sheet_name'], entry['col_start'], entry['location'], entry['final_mapped_type']
            )
            for _, entry in df_mapped.iterrows()
        )
        all_mapped_data = load_all_mapped_data(entry_specs, target_year, bp_data)

        # --- Export report for all mapped valve types and plants --- #
        if len(all_mapped_data) > 0:
            export_bytes = build_export_excel(all_mapped_data)
            st.download_button(
                label="📥 ส่งออก Excel: แยกพื้นที่ / แยกขนาด / อัตราใช้ย้อนหลัง",
                data=export_bytes,
                file_name=f"valve_analysis_{target_year}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="ส่งออกข้อมูลของทุกพื้นที่และทุกชนิดวาล์วที่จับคู่แล้ว พร้อมยอดใช้จริง ยอดโอน และอัตราการใช้รายเดือน"
            )
            st.caption("ไฟล์ส่งออกประกอบด้วย 4 ชีต: รายเดือนแยกพื้นที่/วาล์ว, สรุปพื้นที่, สรุปชนิดวาล์ว และรายการเคลื่อนไหว")
        
        # --- สร้างตัวเลือกวาล์ว พร้อมตัวเลือก 'รวมวาล์วทุกประเภท' --- #
        available_valves_list = sorted([v for v in df_mapped['final_mapped_type'].unique() if v not in ["อื่นๆ / ข้ามรายการนี้", "วาล์วชำรุด"]])
        valve_options = [ALL_VALVES_LABEL] + available_valves_list
        default_v_idx = valve_options.index('วาล์วมือหมุน 15 กก.') if 'วาล์วมือหมุน 15 กก.' in valve_options else 0
        
        # --- TAB NAVIGATION --- #
        tab_history, tab_simulation = st.tabs([
            "📊 1. ข้อมูลจริง & แยกยอดโอน (Historical & Transfers)",
            "🔮 2. แบบจำลองคาดการณ์จัดซื้อล่วงหน้า (Simulation to Month 12)"
        ])
        
        # ========================================================================= #
        # TAB 1: HISTORICAL DATA & TRANSFERS                                        #
        # ========================================================================= #
        with tab_history:
            st.subheader("สรุปสถิติการใช้งานจริง, ยอดโอน และจุดสั่งซื้อซ้ำ")
            sel_c1, sel_c2 = st.columns(2)
            
            selected_valve = sel_c1.selectbox("🎯 1. เลือกขนาดวาล์ว:", valve_options, index=default_v_idx, key="hist_valve")
            is_all_valves = (selected_valve == ALL_VALVES_LABEL)

            if is_all_valves:
                plants_available = sorted(df_mapped[df_mapped['final_mapped_type'].isin(available_valves_list)]['location'].unique())
            else:
                plants_available = sorted(df_mapped[df_mapped['final_mapped_type'] == selected_valve]['location'].unique())
                
            plant_options_view = ["🏢 ทุกพื้นที่รวมกัน (All Plants)"] + [f"📍 {p}" for p in plants_available]
            selected_plant_view = sel_c2.selectbox("🏢 2. เลือกพื้นที่ที่ต้องการดูผล:", plant_options_view, index=0, key="hist_plant")

            # กรอง active entries
            active_types = available_valves_list if is_all_valves else [selected_valve]
            combined_df = all_mapped_data[all_mapped_data['valve_type'].isin(active_types)].copy()

            if len(combined_df) > 0:
                
                # แสดงกล่องสรุปรายการโอนที่ตรวจพบ
                transfer_rows = combined_df[combined_df['is_transfer']].copy()
                with st.expander(f"🚚 คลิกเพื่อดูรายการจ่ายโอนระหว่างคลังที่ตรวจพบ ({len(transfer_rows)} รายการ)", expanded=False):
                    if len(transfer_rows) > 0:
                        st.info("💡 รายการเหล่านี้ถูกตรวจพบว่าเป็นการโอนออกไปคลัง/โรงงานอื่น ไม่ใช่การเบิกใช้ในสายการผลิตจริง")
                        st.dataframe(
                            transfer_rows[['location', 'valve_type', 'day', 'month_num', 'issue_to', 'issue_qty']]
                            .rename(columns={
                                'location': 'พื้นที่', 'valve_type': 'ชนิดวาล์ว', 'day': 'วันที่', 'month_num': 'เดือน',
                                'issue_to': 'จ่ายโอนให้ (ปลายทาง)', 'issue_qty': 'จำนวนที่โอน (ตัว)'
                            }),
                            use_container_width=True
                        )
                    else:
                        st.write("ไม่พบรายการจ่ายที่เป็นการโอนระหว่างคลัง")

                # รวมยอดรายเดือนแบบ Two-Step เพื่อให้ยอดคงเหลือ (Ending Balance) ถูกต้องสำหรับทั้งวาล์วเดี่ยวและรวมทุกวาล์ว
                valve_monthly = combined_df.groupby(['location', 'valve_type', 'month_num']).agg(
                    rcv_qty=('rcv_qty', 'sum'),
                    issue_qty=('issue_qty', 'sum'),
                    actual_issue_qty=('actual_issue_qty', 'sum'),
                    transfer_qty=('transfer_qty', 'sum'),
                    ending_balance=('balance', 'last')
                ).reset_index()

                summary_monthly = valve_monthly.groupby(['location', 'month_num']).agg(
                    total_rcv=('rcv_qty', 'sum'),
                    total_issue=('issue_qty', 'sum'),
                    actual_issue=('actual_issue_qty', 'sum'),
                    transfer_issue=('transfer_qty', 'sum'),
                    ending_balance=('ending_balance', 'sum')
                ).reset_index()

                summary_monthly['year_ce'] = int(target_year - 543)
                summary_monthly['workdays_no_sun'] = summary_monthly.apply(
                    lambda r: count_workdays_no_sunday(r['year_ce'], r['month_num']), axis=1
                ).astype(int)
                
                if exclude_transfers:
                    summary_monthly['burn_rate_used'] = (summary_monthly['actual_issue'] / summary_monthly['workdays_no_sun']).round(1)
                else:
                    summary_monthly['burn_rate_used'] = (summary_monthly['total_issue'] / summary_monthly['workdays_no_sun']).round(1)
                    
                summary_monthly['month_label'] = summary_monthly['month_num'].map(MONTH_TH_NAMES) + f" {target_year}"

                is_all_plants = "ทุกพื้นที่รวมกัน" in selected_plant_view
                current_plant_focus = selected_plant_view.replace("📍 ", "")
                burn_rate_header = "อัตราใช้จริงเฉลี่ย (ตัว/วัน)" if exclude_transfers else "อัตราจ่ายรวมเฉลี่ย (ตัว/วัน)"

                st.markdown("---")
                st.subheader(f"📊 สรุปข้อมูลการใช้งาน: {selected_valve} [{selected_plant_view}]")

                if not is_all_plants:
                    df_filtered = summary_monthly[summary_monthly['location'] == current_plant_focus].copy()
                    st.dataframe(
                        df_filtered[['month_label', 'total_rcv', 'actual_issue', 'transfer_issue', 'total_issue', 'ending_balance', 'workdays_no_sun', 'burn_rate_used']]
                        .rename(columns={
                            'month_label': 'เดือน', 'total_rcv': 'ยอดรับเข้า (ตัว)',
                            'actual_issue': 'เบิกใช้จริงใน รง. (ตัว)', 'transfer_issue': 'โอนไปคลังอื่น (ตัว)',
                            'total_issue': 'จ่ายรวมทั้งหมด (ตัว)', 'ending_balance': 'คงเหลือสิ้นเดือน (ตัว)',
                            'workdays_no_sun': 'วันทำงานจริง (จ.-ส.)', 'burn_rate_used': burn_rate_header
                        }), use_container_width=True
                    )
                else:
                    t1, t2 = st.tabs(["📋 สรุปรวมทุกพื้นที่", "🏢 สรุปแยกแต่ละโรงงาน"])
                    with t1:
                        comb_m = combined_df.groupby('month_num').agg(
                            total_rcv=('rcv_qty', 'sum'),
                            actual_issue=('actual_issue_qty', 'sum'),
                            transfer_issue=('transfer_qty', 'sum'),
                            total_issue=('issue_qty', 'sum')
                        ).reset_index()
                        bal_m = summary_monthly.groupby('month_num')['ending_balance'].sum().reset_index()
                        comb_m = comb_m.merge(bal_m, on='month_num')
                        comb_m['year_ce'] = int(target_year - 543)
                        comb_m['workdays_no_sun'] = comb_m['month_num'].apply(lambda m: count_workdays_no_sunday(target_year - 543, m)).astype(int)
                        
                        if exclude_transfers:
                            comb_m['burn_rate_used'] = (comb_m['actual_issue'] / comb_m['workdays_no_sun']).round(1)
                        else:
                            comb_m['burn_rate_used'] = (comb_m['total_issue'] / comb_m['workdays_no_sun']).round(1)
                            
                        comb_m['month_label'] = comb_m['month_num'].map(MONTH_TH_NAMES) + f" {target_year}"
                        st.dataframe(comb_m[['month_label', 'total_rcv', 'actual_issue', 'transfer_issue', 'total_issue', 'ending_balance', 'workdays_no_sun', 'burn_rate_used']].rename(
                            columns={'month_label': 'เดือน', 'total_rcv': 'ยอดรับรวม', 'actual_issue': 'เบิกใช้จริงรวม', 'transfer_issue': 'โอนไปคลังอื่นรวม', 'total_issue': 'จ่ายรวมทั้งหมด', 'ending_balance': 'คงเหลือรวม', 'workdays_no_sun': 'วันทำงาน', 'burn_rate_used': burn_rate_header}), use_container_width=True)
                    with t2:
                        st.dataframe(summary_monthly[['location', 'month_label', 'total_rcv', 'actual_issue', 'transfer_issue', 'total_issue', 'ending_balance', 'workdays_no_sun', 'burn_rate_used']].rename(
                            columns={'location': 'พื้นที่', 'month_label': 'เดือน', 'total_rcv': 'ยอดรับ', 'actual_issue': 'ใช้จริง', 'transfer_issue': 'โอนออก', 'total_issue': 'จ่ายรวม', 'ending_balance': 'คงเหลือ', 'workdays_no_sun': 'วันทำงาน', 'burn_rate_used': burn_rate_header}), use_container_width=True)

                # หากเลือก 'รวมวาล์วทุกประเภท' ให้แสดงตารางแจกแจงตามประเภทวาล์ว (Breakdown Table)
                if is_all_valves:
                    st.write("#### 📑 สัดส่วนและยอดการใช้งานแจกแจงตามประเภทวาล์ว (Breakdown by Valve Type):")
                    target_scope_df = valve_monthly if is_all_plants else valve_monthly[valve_monthly['location'] == current_plant_focus]
                    latest_m = target_scope_df['month_num'].max()
                    
                    valve_bd_summary = []
                    for v in target_scope_df['valve_type'].unique():
                        v_sub = target_scope_df[target_scope_df['valve_type'] == v]
                        v_latest = v_sub[v_sub['month_num'] == latest_m]
                        c_stock = v_latest['ending_balance'].sum() if len(v_latest) > 0 else 0
                        tot_act = v_sub['actual_issue_qty'].sum()
                        tot_trf = v_sub['transfer_qty'].sum()
                        tot_all = v_sub['issue_qty'].sum()
                        wd_last = count_workdays_no_sunday(target_year - 543, latest_m)
                        d_burn = round((v_latest['actual_issue_qty'].sum() if exclude_transfers else v_latest['issue_qty'].sum()) / wd_last, 1) if len(v_latest) > 0 else 0.0
                        
                        valve_bd_summary.append({
                            'ชนิดวาล์ว': v,
                            'สต็อกคงเหลือล่าสุด (ตัว)': int(c_stock),
                            'ยอดใช้จริงสะสม (ตัว)': int(tot_act),
                            'ยอดโอนออกสะสม (ตัว)': int(tot_trf),
                            'ยอดจ่ายรวมสะสม (ตัว)': int(tot_all),
                            'อัตราใช้เดือนล่าสุด (ตัว/วัน)': d_burn
                        })
                    df_v_bd = pd.DataFrame(valve_bd_summary).sort_values('สต็อกคงเหลือล่าสุด (ตัว)', ascending=False)
                    st.dataframe(df_v_bd, use_container_width=True)

                # แผนสั่งซื้อ ROP ปัจจุบัน
                latest_months = summary_monthly.groupby('location')['month_num'].max().reset_index()
                latest_summary = pd.merge(summary_monthly, latest_months, on=['location', 'month_num'])
                if not is_all_plants:
                    latest_summary = latest_summary[latest_summary['location'] == current_plant_focus]
                plan_rows = []
                for _, r in latest_summary.iterrows():
                    daily = r['burn_rate_used']
                    curr = r['ending_balance']
                    ss = round(daily * safety_stock_days)
                    rop = round((daily * lead_time_days) + ss)
                    cov_days = round(curr / daily, 1) if daily > 0 else 999
                    status = "🚨 สั่งซื้อด่วน (Stock < ROP)" if curr <= rop else "✅ สต็อกเพียงพอ (Safe)"
                    order_qty = round((daily * order_cycle_days) + (rop - curr), -2) if curr <= rop else 0
                    plan_rows.append({
                        'พื้นที่': r['location'], 'ข้อมูลล่าสุด': r['month_label'], 'อัตราใช้เกณฑ์ (ตัว/วัน)': daily,
                        'สต็อกปัจจุบัน (ตัว)': int(curr), 'Safety Stock (ตัว)': ss, 'จุดสั่งซื้อ ROP (ตัว)': rop,
                        'สต็อกอยู่ได้อีก (วันทำงาน)': cov_days, 'สถานะ': status, 'จำนวนแนะนำสั่งซื้อ (ตัว)': int(order_qty)
                    })
                st.write(f"**สถานะสต็อกปัจจุบันเทียบกับจุดสั่งซื้อ (ROP) [{('ตัดยอดโอนออก' if exclude_transfers else 'รวมยอดโอน')}]:**")
                st.dataframe(pd.DataFrame(plan_rows), use_container_width=True)
            else:
                st.warning("ไม่พบข้อมูลประวัติสำหรับรายการที่เลือก")

        # ========================================================================= #
        # TAB 2: FUTURE PROCUREMENT SIMULATOR                                       #
        # ========================================================================= #
        with tab_simulation:
            st.subheader("🔮 แบบจำลองคาดการณ์ความต้องการใช้วาล์ว & คำนวณยอดติดลบล่วงหน้า")
            st.markdown("ระบบจะดึง **สต็อกคงเหลือล่าสุด** และ **อัตราการใช้จริงต่อวัน (ตัดยอดโอนออก)** เพื่อจำลอง Forward Projection จนถึงเดือนเป้าหมาย")

            sim_c1, sim_c2, sim_c3 = st.columns([2, 2, 2])
            sim_selected_valve = sim_c1.selectbox("🎯 1. เลือกขนาดวาล์วที่จะ Simulate:", valve_options, index=default_v_idx, key="sim_valve")
            is_sim_all_valves = (sim_selected_valve == ALL_VALVES_LABEL)

            if is_sim_all_valves:
                sim_plants_available = sorted(df_mapped[df_mapped['final_mapped_type'].isin(available_valves_list)]['location'].unique())
                sim_entries = df_mapped[df_mapped['final_mapped_type'].isin(available_valves_list)]
            else:
                sim_plants_available = sorted(df_mapped[df_mapped['final_mapped_type'] == sim_selected_valve]['location'].unique())
                sim_entries = df_mapped[df_mapped['final_mapped_type'] == sim_selected_valve]

            sim_plant_view = sim_c2.selectbox("🏢 2. เลือกพื้นที่ (Plant):", ["🏢 ทุกพื้นที่รวมกัน (All Plants)"] + [f"📍 {p}" for p in sim_plants_available], key="sim_plant")
            target_future_month = sim_c3.slider("📅 3. คาดการณ์ไปจนถึงสิ้นเดือน:", min_value=8, max_value=12, value=12, format="เดือน %d")

            sim_types = available_valves_list if is_sim_all_valves else [sim_selected_valve]
            sim_comb_df = all_mapped_data[all_mapped_data['valve_type'].isin(sim_types)].copy()

            if len(sim_comb_df) > 0:
                
                # Two-step aggregation
                sim_valve_monthly = sim_comb_df.groupby(['location', 'valve_type', 'month_num']).agg(
                    issue_qty=('issue_qty', 'sum'),
                    actual_issue_qty=('actual_issue_qty', 'sum'),
                    ending_balance=('balance', 'last')
                ).reset_index()

                sim_summary = sim_valve_monthly.groupby(['location', 'month_num']).agg(
                    total_issue=('issue_qty', 'sum'),
                    actual_issue=('actual_issue_qty', 'sum'),
                    ending_balance=('ending_balance', 'sum')
                ).reset_index()

                sim_summary['year_ce'] = int(target_year - 543)
                sim_summary['workdays_no_sun'] = sim_summary.apply(
                    lambda r: count_workdays_no_sunday(r['year_ce'], r['month_num']), axis=1
                ).astype(int)
                
                if exclude_transfers:
                    sim_summary['daily_rate'] = (sim_summary['actual_issue'] / sim_summary['workdays_no_sun']).round(1)
                else:
                    sim_summary['daily_rate'] = (sim_summary['total_issue'] / sim_summary['workdays_no_sun']).round(1)

                is_sim_all = "ทุกพื้นที่รวมกัน" in sim_plant_view
                sim_focus_plant = sim_plant_view.replace("📍 ", "")

                # Simulation Settings
                st.markdown("---")
                st.write("**⚙️ พารามิเตอร์การจำลอง (Simulation Assumptions):**")
                pcol1, pcol2, pcol3 = st.columns(3)
                
                rate_method = pcol1.radio(
                    f"เกณฑ์อัตราใช้ต่อวัน ({'ใช้เฉพาะยอดใช้จริง' if exclude_transfers else 'รวมยอดโอน'}):",
                    ["ใช้อัตราเดือนล่าสุด (Latest Month)", "ใช้ค่าเฉลี่ย 3 เดือนล่าสุด (Last 3 Months Avg)"],
                    index=0
                )
                growth_rate_pct = pcol2.number_input("ปรับอัตราใช้ตามฤดูกาล / การเติบโต (+/- %):", value=0, step=5, help="เช่น ปลายปีใช้เยอะขึ้น +10%")
                sim_safety_days = pcol3.number_input("Safety Stock สำรองปลายงวด (วันทำงาน):", min_value=0, max_value=45, value=7)

                # Calculate base stock and base daily rate
                if not is_sim_all:
                    p_data = sim_summary[sim_summary['location'] == sim_focus_plant].sort_values('month_num')
                    last_row = p_data.iloc[-1]
                    latest_month_num = int(last_row['month_num'])
                    base_stock = last_row['ending_balance']
                    
                    if "3 เดือน" in rate_method:
                        base_daily = p_data.tail(3)['daily_rate'].mean()
                    else:
                        base_daily = last_row['daily_rate']
                else:
                    latest_month_num = int(sim_summary['month_num'].max())
                    base_stock = sim_summary[sim_summary['month_num'] == latest_month_num]['ending_balance'].sum()
                    comb_month_rate = sim_summary.groupby('month_num')['daily_rate'].sum().reset_index()
                    if "3 เดือน" in rate_method:
                        base_daily = comb_month_rate.tail(3)['daily_rate'].mean()
                    else:
                        base_daily = comb_month_rate[comb_month_rate['month_num'] == latest_month_num]['daily_rate'].values[0]

                adjusted_daily = round(base_daily * (1.0 + (growth_rate_pct / 100.0)), 1)
                
                start_sim_month = latest_month_num + 1
                if start_sim_month > target_future_month:
                    st.info(f"ข้อมูลจริงมีบันทึกถึงเดือน {latest_month_num} แล้ว ซึ่งครอบคลุมหรือมากกว่าเดือนเป้าหมาย ({target_future_month})")
                else:
                    with st.expander(f"📥 กำหนดแผนรับของเข้าล่วงหน้า (ถ้ามี PO ที่สั่งไปแล้วและกำลังจะมาส่งในเดือน {start_sim_month} - {target_future_month})", expanded=False):
                        st.caption("หากยังไม่มีแผนส่งมอบ ให้ใส่เป็น 0")
                        planned_receipts = {}
                        inflow_cols = st.columns(target_future_month - start_sim_month + 1)
                        for col_idx, m in enumerate(range(start_sim_month, target_future_month + 1)):
                            m_name = MONTH_TH_NAMES[m]
                            planned_receipts[m] = inflow_cols[col_idx].number_input(f"รับเข้า {m_name}:", min_value=0, value=0, step=1000, key=f"inflow_{m}")

                    # Run Month-by-Month Simulation
                    sim_rows = []
                    current_sim_stock = base_stock
                    stockout_month = None
                    total_future_demand = 0
                    total_future_inflow = 0
                    
                    year_ce = target_year - 543
                    for m in range(start_sim_month, target_future_month + 1):
                        wd = count_workdays_no_sunday(year_ce, m)
                        demand = round(wd * adjusted_daily)
                        inflow = planned_receipts.get(m, 0)
                        end_sim_stock = current_sim_stock + inflow - demand
                        
                        total_future_demand += demand
                        total_future_inflow += inflow
                        
                        if end_sim_stock < 0 and stockout_month is None:
                            stockout_month = f"{MONTH_TH_NAMES[m]} {target_year}"
                            
                        sim_rows.append({
                            'เดือน': f"{MONTH_TH_NAMES[m]} {target_year}",
                            'วันทำงาน (จ.-ส.)': wd,
                            'สต็อกยกมา (ตัว)': int(current_sim_stock),
                            'แผนรับเข้า (ตัว)': int(inflow),
                            'คาดการณ์ใช้ (ตัว)': int(demand),
                            'สต็อกคงเหลือปลายเดือน (ตัว)': int(end_sim_stock),
                            'สถานะ': "🚨 สินค้าขาดมือ (Deficit)" if end_sim_stock < 0 else "✅ สต็อกบวก (OK)"
                        })
                        current_sim_stock = end_sim_stock
                        
                    df_sim_result = pd.DataFrame(sim_rows)
                    
                    final_ending_stock = current_sim_stock
                    target_safety_stock = round(adjusted_daily * sim_safety_days)
                    net_needed = max(0, target_safety_stock - final_ending_stock)
                    suggested_po_qty = int(np.ceil(net_needed / 100.0) * 100)

                    # --- KPI METRIC DISPLAY --- #
                    st.markdown("---")
                    st.write("### 📌 สรุปผลการจำลองการจัดซื้อ (Simulation KPI Summary)")
                    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                    
                    kpi1.metric(
                        label="📦 สต็อกตั้งต้น (สิ้นเดือนล่าสุด)",
                        value=f"{int(base_stock):,} ตัว",
                        delta=f"อัตราใช้ {adjusted_daily:,.1f} ตัว/วัน"
                    )
                    
                    kpi2.metric(
                        label="⚠️ เดือนที่สินค้าจะเริ่มขาดมือ",
                        value=stockout_month if stockout_month else "ไม่ขาดมือ (Stock OK)",
                        delta="วิกฤต" if stockout_month else "ปลอดภัย",
                        delta_color="inverse" if stockout_month else "normal"
                    )
                    
                    kpi3.metric(
                        label=f"📉 สต็อกปลายงวด ณ สิ้นเดือน {target_future_month}",
                        value=f"{int(final_ending_stock):,} ตัว",
                        delta="ติดลบ" if final_ending_stock < 0 else "คงเหลือ",
                        delta_color="inverse" if final_ending_stock < 0 else "normal"
                    )
                    
                    kpi4.metric(
                        label="🛒 ปริมาณที่ต้องจัดซื้อเพิ่ม (ครอบคลุมถึงสิ้นงวด)",
                        value=f"{suggested_po_qty:,} ตัว",
                        delta=f"รวมสำรอง SS {target_safety_stock:,} ตัว"
                    )

                    # --- SIMULATION TIMELINE TABLE --- #
                    st.write(f"#### 📋 ตารางจำลองสต็อกคงเหลือทีละเดือน (จนถึงสิ้นเดือน {MONTH_TH_NAMES[target_future_month]} {target_year}):")
                    st.dataframe(df_sim_result, use_container_width=True)

                    # --- BREAKDOWN TABLE BY VALVE TYPE IF ALL VALVES SELECTED --- #
                    if is_sim_all_valves:
                        st.write("#### 📑 แจกแจงการคาดการณ์และยอดสั่งซื้อแยกตามประเภทวาล์ว (Breakdown per Valve Type):")
                        target_v_df = sim_valve_monthly if is_sim_all else sim_valve_monthly[sim_valve_monthly['location'] == sim_focus_plant]
                        sim_breakdown = []
                        total_future_workdays = sum(count_workdays_no_sunday(year_ce, fm) for fm in range(start_sim_month, target_future_month + 1))
                        
                        for v_name in target_v_df['valve_type'].unique():
                            sub_v = target_v_df[target_v_df['valve_type'] == v_name]
                            sub_last = sub_v[sub_v['month_num'] == latest_month_num]
                            c_stk = sub_last['ending_balance'].sum() if len(sub_last) > 0 else 0
                            wd_l = count_workdays_no_sunday(year_ce, latest_month_num)
                            
                            v_daily = round((sub_last['actual_issue_qty'].sum() if exclude_transfers else sub_last['issue_qty'].sum()) / wd_l, 1) if len(sub_last) > 0 else 0.0
                            v_adj_daily = round(v_daily * (1.0 + (growth_rate_pct / 100.0)), 1)
                            v_future_demand = round(total_future_workdays * v_adj_daily)
                            v_proj_stock = c_stk - v_future_demand
                            v_ss = round(v_adj_daily * sim_safety_days)
                            v_needed = max(0, v_ss - v_proj_stock)
                            v_sugg_po = int(np.ceil(v_needed / 100.0) * 100)
                            
                            sim_breakdown.append({
                                'ชนิดวาล์ว': v_name,
                                'สต็อกปัจจุบัน (ตัว)': int(c_stk),
                                'อัตราใช้จริง (ตัว/วัน)': v_adj_daily,
                                f'ความต้องการใช้ถึงเดือน {target_future_month} (ตัว)': v_future_demand,
                                f'สต็อกคงเหลือปลายเดือน {target_future_month} (ตัว)': int(v_proj_stock),
                                'Safety Stock สำรอง': v_ss,
                                'จำนวนแนะนำสั่งซื้อ (ตัว)': v_sugg_po,
                                'สถานะ': "🚨 สินค้าขาดมือ" if v_proj_stock < 0 else "✅ เพียงพอ"
                            })
                        df_sim_bd = pd.DataFrame(sim_breakdown).sort_values('จำนวนแนะนำสั่งซื้อ (ตัว)', ascending=False)
                        st.dataframe(df_sim_bd, use_container_width=True)

                    # --- PROJECTION CHART --- #
                    st.write("#### 📉 กราฟจำลองแนวโน้มการลดลงของสต็อก (Inventory Run-down Curve):")
                    
                    chart_months = [f"{MONTH_TH_NAMES[latest_month_num]} (จริง)"] + list(df_sim_result['เดือน'])
                    chart_stocks = [base_stock] + list(df_sim_result['สต็อกคงเหลือปลายเดือน (ตัว)'])
                    
                    fig_sim = go.Figure()
                    
                    fig_sim.add_trace(go.Scatter(
                        x=chart_months,
                        y=chart_stocks,
                        mode='lines+markers+text',
                        name='สต็อกคงเหลือคาดการณ์',
                        text=[f"{int(s):,}" for s in chart_stocks],
                        textposition="top right",
                        line=dict(color='#d62728' if final_ending_stock < 0 else '#2ca02c', width=3)
                    ))
                    
                    fig_sim.add_hline(y=0, line_dash="dash", line_color="black", annotation_text="จุดของหมด (Zero Stock)", annotation_position="bottom left")
                    
                    if target_safety_stock > 0:
                        fig_sim.add_hline(y=target_safety_stock, line_dash="dot", line_color="orange", annotation_text=f"Safety Stock ({target_safety_stock:,} ตัว)", annotation_position="top left")
                        
                    fig_sim.update_layout(
                        title=f"การคาดการณ์สต็อก {sim_selected_valve} ({sim_plant_view}) จนถึงเดือน {MONTH_TH_NAMES[target_future_month]} {target_year}",
                        xaxis_title="เดือน",
                        yaxis_title="จำนวนสต็อกคงเหลือ (ตัว)",
                        hovermode="x unified"
                    )
                    st.plotly_chart(fig_sim, use_container_width=True)
            else:
                st.warning("ไม่พบข้อมูลสำหรับจำลองการจัดซื้อ")
else:
    st.info("👆 กรุณาอัปโหลดไฟล์ Excel ของคลังต่างๆ ด้านบน เพื่อเริ่มต้นวิเคราะห์และจำลองแผนจัดซื้อ")