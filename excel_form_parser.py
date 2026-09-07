import io
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import xlrd
except ImportError:
    xlrd = None

try:
    import openpyxl
except ImportError:
    openpyxl = None


@dataclass
class FormStudentItem:
    """Mô tả một sinh viên trích xuất từ file Form Excel"""
    stt: int = 0
    fpt_id: str = ""
    greenwich_id: str = ""
    email: str = ""
    full_name: str = ""
    paper_id: str = ""
    moodle_shell: str = ""
    class_code: str = ""
    lecturer: str = ""
    cohort: str = ""
    has_paper_id: bool = False
    extra_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["has_paper_id"] = bool(self.paper_id and self.paper_id.strip())
        return d


@dataclass
class FormSheetData:
    """Mô tả dữ liệu của một Sheet trong file Form Excel"""
    sheet_name: str
    sheet_type: str = "generic"  # "computing", "business", "generic", "skip"
    course_code: str = ""
    course_title: str = ""
    assessment_title: str = ""
    first_marker: str = ""
    total_students: int = 0
    students_with_paper_id: int = 0
    classes: List[str] = field(default_factory=list)
    students: List[FormStudentItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sheet_name": self.sheet_name,
            "sheet_type": self.sheet_type,
            "course_code": self.course_code,
            "course_title": self.course_title,
            "assessment_title": self.assessment_title,
            "first_marker": self.first_marker,
            "total_students": self.total_students,
            "students_with_paper_id": self.students_with_paper_id,
            "classes": self.classes,
            "students": [s.to_dict() for s in self.students]
        }


@dataclass
class FormParseResult:
    """Kết quả tổng thể sau khi phân tích file Form Excel"""
    filename: str
    file_type: str  # "xls" hoặc "xlsx"
    sheets: List[FormSheetData] = field(default_factory=list)
    primary_sheet_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "file_type": self.file_type,
            "primary_sheet_name": self.primary_sheet_name,
            "sheets": [s.to_dict() for s in self.sheets if s.sheet_type != "skip"]
        }


def _clean_cell_str(val: Any) -> str:
    """Làm sạch giá trị ô Excel thành chuỗi văn bản chuẩn"""
    if val is None:
        return ""
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val))
        return str(val)
    if isinstance(val, int):
        return str(val)
    return str(val).strip()


def _clean_id_str(val: Any) -> str:
    """Làm sạch Paper ID hoặc Greenwich ID tránh lỗi số float (VD: 287632096.0 -> 287632096)"""
    s = _clean_cell_str(val)
    if not s or s.lower() in ["none", "null", "-", "--"]:
        return ""
    # Loại bỏ đuôi .0 nếu có
    if re.match(r'^\d+\.0$', s):
        s = s[:-2]
    # Chỉ giữ lại các chữ số nếu là ID thuần số
    m = re.match(r'^(\d+)', s)
    if m and len(m.group(1)) >= 6:
        return m.group(1)
    return s


def parse_excel_file(file_source: Union[str, Path, bytes], filename: str = "") -> FormParseResult:
    """
    Hàm phân tích tổng quát tiếp nhận đường dẫn file hoặc nội dung bytes của file .xls / .xlsx.
    Tự động nhận diện định dạng và bóc tách dữ liệu.
    """
    if isinstance(file_source, (str, Path)):
        p = Path(file_source)
        if not filename:
            filename = p.name
        ext = p.suffix.lower().lstrip(".")
        with open(p, "rb") as f:
            content_bytes = f.read()
    else:
        content_bytes = file_source
        if not filename:
            filename = "uploaded_form.xls"
        ext = "xlsx" if filename.lower().endswith(".xlsx") else "xls"

    if ext == "xlsx":
        return _parse_openpyxl(content_bytes, filename)
    else:
        return _parse_xlrd(content_bytes, filename)


def _parse_xlrd(content_bytes: bytes, filename: str) -> FormParseResult:
    if xlrd is None:
        raise ImportError("Thư viện 'xlrd' chưa được cài đặt để đọc file .xls.")

    wb = xlrd.open_workbook(file_contents=content_bytes, formatting_info=False)
    result = FormParseResult(filename=filename, file_type="xls")

    primary_sheet_found = False

    for sname in wb.sheet_names():
        # Bỏ qua các sheet không chứa điểm như Guidance, Statistics
        lower_sname = sname.lower()
        if any(k in lower_sname for k in ["guidance", "statistic", "instruction", "readme"]):
            sheet_data = FormSheetData(sheet_name=sname, sheet_type="skip")
            result.sheets.append(sheet_data)
            continue

        sheet = wb.sheet_by_name(sname)
        rows: List[List[str]] = []
        for r in range(sheet.nrows):
            row_vals = [_clean_cell_str(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
            rows.append(row_vals)

        sheet_data = _analyze_and_extract_sheet_rows(sname, rows)
        result.sheets.append(sheet_data)

    # Chọn primary sheet ưu tiên sheet có điểm số cao nhất (nhiều sinh viên & có Paper ID)
    best_sheet = ""
    best_score = -1
    for s in result.sheets:
        if s.sheet_type == "skip":
            continue
        score = s.total_students + (s.students_with_paper_id * 2)
        if score > best_score:
            best_score = score
            best_sheet = s.sheet_name
    result.primary_sheet_name = best_sheet

    return result


def _parse_openpyxl(content_bytes: bytes, filename: str) -> FormParseResult:
    if openpyxl is None:
        raise ImportError("Thư viện 'openpyxl' chưa được cài đặt để đọc file .xlsx.")

    wb = openpyxl.load_workbook(io.BytesIO(content_bytes), data_only=True)
    result = FormParseResult(filename=filename, file_type="xlsx")

    primary_sheet_found = False

    for sname in wb.sheetnames:
        lower_sname = sname.lower()
        if any(k in lower_sname for k in ["guidance", "statistic", "instruction", "readme"]):
            sheet_data = FormSheetData(sheet_name=sname, sheet_type="skip")
            result.sheets.append(sheet_data)
            continue

        sheet = wb[sname]
        rows: List[List[str]] = []
        for row in sheet.iter_rows(values_only=True):
            row_vals = [_clean_cell_str(c) for c in row]
            rows.append(row_vals)

        sheet_data = _analyze_and_extract_sheet_rows(sname, rows)
        result.sheets.append(sheet_data)

    # Chọn primary sheet ưu tiên sheet có điểm số cao nhất (nhiều sinh viên & có Paper ID)
    best_sheet = ""
    best_score = -1
    for s in result.sheets:
        if s.sheet_type == "skip":
            continue
        score = s.total_students + (s.students_with_paper_id * 2)
        if score > best_score:
            best_score = score
            best_sheet = s.sheet_name
    result.primary_sheet_name = best_sheet

    return result


def _analyze_and_extract_sheet_rows(sheet_name: str, rows: List[List[str]]) -> FormSheetData:
    """
    Phân tích một ma trận các ô của Sheet để xác định template và trích xuất thông tin
    """
    sheet_data = FormSheetData(sheet_name=sheet_name)
    if not rows:
        sheet_data.sheet_type = "skip"
        return sheet_data

    # Gom toàn bộ text trong 15 dòng đầu để nhận diện mẫu form
    top_text = " ".join(" ".join(r) for r in rows[:15]).lower()

    is_computing = "faculty of computing" in top_text or "fpt id" in top_text or "moodle shell" in top_text
    is_business = "business school" in top_text or "assess't title" in top_text or "portfolio" in top_text

    if is_computing:
        sheet_data.sheet_type = "computing"
        _extract_computing_sheet(rows, sheet_data)
    elif is_business:
        sheet_data.sheet_type = "business"
        _extract_business_sheet(rows, sheet_data)
    else:
        # Generic: cố gắng tìm bảng dữ liệu sinh viên thông thường
        sheet_data.sheet_type = "generic"
        _extract_generic_sheet(rows, sheet_data)

    sheet_data.total_students = len(sheet_data.students)
    sheet_data.students_with_paper_id = sum(1 for s in sheet_data.students if s.has_paper_id)
    sheet_data.classes = sorted(list({s.moodle_shell for s in sheet_data.students if s.moodle_shell}))

    return sheet_data


def _find_field_value_in_rows(rows: List[List[str]], label_regex: str, max_rows: int = 15) -> str:
    """Tìm giá trị nằm bên phải hoặc bên dưới của một nhãn (Label)"""
    pattern = re.compile(label_regex, re.IGNORECASE)
    for r_idx, row in enumerate(rows[:max_rows]):
        for c_idx, cell in enumerate(row):
            if pattern.search(cell):
                # 1. Tìm ô không rỗng đầu tiên bên phải trong cùng dòng
                for next_c in range(c_idx + 1, len(row)):
                    val = row[next_c].strip()
                    # Bỏ qua nếu là nhãn kế tiếp
                    if val and not pattern.search(val):
                        # Nếu ô chứa cả label và value (VD: "Course Code: COMP1787")
                        return val
                # 2. Hoặc nếu cell chứa luôn cả giá trị sau dấu hai chấm
                if ":" in cell:
                    parts = cell.split(":", 1)
                    if len(parts) > 1 and parts[1].strip():
                        return parts[1].strip()
    return ""


def _extract_computing_sheet(rows: List[List[str]], sheet_data: FormSheetData):
    """Trích xuất theo chuẩn Faculty of Computing Mark Sheet"""
    # 1. Metadata
    sheet_data.course_code = _find_field_value_in_rows(rows, r'Course Code')
    # Chuẩn hóa mã môn: COMP1787 -> COMP1787
    if sheet_data.course_code:
        sheet_data.course_code = re.sub(r'[^A-Za-z0-9]', '', sheet_data.course_code).upper()

    sheet_data.course_title = _find_field_value_in_rows(rows, r'Course Title')
    sheet_data.assessment_title = _find_field_value_in_rows(rows, r'Assessment Title')
    sheet_data.first_marker = _find_field_value_in_rows(rows, r'First Marker')

    # 2. Tìm dòng Header của bảng sinh viên
    header_row_idx = -1
    col_map: Dict[str, int] = {}

    for r_idx, row in enumerate(rows[:20]):
        row_str = " ".join(row).lower()
        if "fpt id" in row_str or "greenwich id" in row_str or "paper id" in row_str:
            header_row_idx = r_idx
            for c_idx, cell in enumerate(row):
                cl = cell.lower()
                if "fpt id" in cl:
                    col_map["fpt_id"] = c_idx
                elif "greenwich id" in cl or "student id" in cl:
                    col_map["greenwich_id"] = c_idx
                elif "email" in cl:
                    col_map["email"] = c_idx
                elif "full name" in cl or "student name" in cl:
                    col_map["full_name"] = c_idx
                elif "paper id" in cl:
                    col_map["paper_id"] = c_idx
                elif "cohort" in cl:
                    col_map["cohort"] = c_idx
                elif "moodle shell" in cl:
                    col_map["moodle_shell"] = c_idx
                elif "class code" in cl:
                    col_map["class_code"] = c_idx
                elif "lecturer" in cl:
                    col_map["lecturer"] = c_idx
            break

    if header_row_idx == -1:
        return

    # 3. Lặp qua các dòng sinh viên từ sau dòng header
    stt_counter = 1
    for r_idx in range(header_row_idx + 1, len(rows)):
        row = rows[r_idx]
        if not any(row):
            continue

        # Kiểm tra xem có phải dòng giải thích sub-header không (VD: "000- - - - - -")
        row_str = " ".join(row)
        if "000- - - - - -" in row_str or "1st maker" in row_str.lower() or "eg sep.10" in row_str.lower():
            continue

        def get_col(col_key: str) -> str:
            idx = col_map.get(col_key, -1)
            if idx != -1 and idx < len(row):
                return row[idx]
            return ""

        fpt_id = get_col("fpt_id").strip()
        greenwich_id = _clean_id_str(get_col("greenwich_id"))
        email = get_col("email").strip()
        full_name = get_col("full_name").strip()
        paper_id = _clean_id_str(get_col("paper_id"))
        moodle_shell = get_col("moodle_shell").strip()
        class_code = get_col("class_code").strip()
        lecturer = get_col("lecturer").strip()
        cohort = get_col("cohort").strip()

        # Dòng hợp lệ phải có ít nhất họ tên, hoặc MSSV, hoặc FPT ID
        if not (full_name or fpt_id or greenwich_id):
            continue

        # Bỏ qua các dòng tổng kết (VD: Average, Count, Max, Min)
        if any(k in full_name.lower() for k in ["average", "total", "count", "maximum", "minimum"]):
            continue

        student = FormStudentItem(
            stt=stt_counter,
            fpt_id=fpt_id,
            greenwich_id=greenwich_id,
            email=email,
            full_name=full_name,
            paper_id=paper_id,
            moodle_shell=moodle_shell,
            class_code=class_code,
            lecturer=lecturer,
            cohort=cohort,
            has_paper_id=bool(paper_id)
        )
        sheet_data.students.append(student)
        stt_counter += 1


def _extract_business_sheet(rows: List[List[str]], sheet_data: FormSheetData):
    """Trích xuất theo chuẩn Business School Marking Form (Portfolio, Contribution,...)"""
    sheet_data.course_code = _find_field_value_in_rows(rows, r'Course Code')
    if sheet_data.course_code:
        sheet_data.course_code = sheet_data.course_code.replace(" ", "").upper()

    sheet_data.course_title = _find_field_value_in_rows(rows, r'Course Title')
    sheet_data.assessment_title = _find_field_value_in_rows(rows, r"Assess't Title|Assessment Title")
    if not sheet_data.assessment_title:
        sheet_data.assessment_title = sheet_data.sheet_name

    sheet_data.first_marker = _find_field_value_in_rows(rows, r'First Marker')

    header_row_idx = -1
    col_map: Dict[str, int] = {}

    for r_idx, row in enumerate(rows[:20]):
        row_str = " ".join(row).lower()
        if "greenwich id" in row_str or ("last name" in row_str and "first name" in row_str):
            header_row_idx = r_idx
            for c_idx, cell in enumerate(row):
                cl = cell.lower()
                if "greenwich id" in cl or "student id" in cl:
                    col_map["greenwich_id"] = c_idx
                elif "last name" in cl:
                    col_map["last_name"] = c_idx
                elif "first name" in cl:
                    col_map["first_name"] = c_idx
                elif "cohort" in cl:
                    col_map["cohort"] = c_idx
                elif "paper id" in cl:
                    col_map["paper_id"] = c_idx
            break

    if header_row_idx == -1:
        return

    stt_counter = 1
    for r_idx in range(header_row_idx + 1, len(rows)):
        row = rows[r_idx]
        if not any(row):
            continue

        row_str = " ".join(row)
        if "000- - - - - -" in row_str or "1st mark" in row_str.lower() or "eg sep.10" in row_str.lower():
            continue

        def get_col(col_key: str) -> str:
            idx = col_map.get(col_key, -1)
            if idx != -1 and idx < len(row):
                return row[idx]
            return ""

        greenwich_id = _clean_id_str(get_col("greenwich_id"))
        last_name = get_col("last_name").strip()
        first_name = get_col("first_name").strip()
        cohort = get_col("cohort").strip()
        paper_id = _clean_id_str(get_col("paper_id"))

        if not (greenwich_id or last_name or first_name):
            continue

        # Tạo họ tên đầy đủ
        if last_name and first_name:
            full_name = f"{last_name} {first_name}".strip()
        else:
            full_name = last_name or first_name

        if any(k in full_name.lower() for k in ["average", "total", "count", "maximum", "minimum"]):
            continue

        student = FormStudentItem(
            stt=stt_counter,
            greenwich_id=greenwich_id,
            full_name=full_name,
            paper_id=paper_id,
            cohort=cohort,
            has_paper_id=bool(paper_id)
        )
        sheet_data.students.append(student)
        stt_counter += 1


def _extract_generic_sheet(rows: List[List[str]], sheet_data: FormSheetData):
    """Trích xuất dự phòng cho file bảng điểm tùy biến"""
    header_row_idx = -1
    col_map: Dict[str, int] = {}

    for r_idx, row in enumerate(rows[:25]):
        for c_idx, cell in enumerate(row):
            cl = cell.lower()
            if any(k in cl for k in ["student id", "mssv", "greenwich id", "fpt id", "mã sv"]):
                col_map["id"] = c_idx
            elif any(k in cl for k in ["full name", "họ tên", "student name", "tên sinh viên"]):
                col_map["name"] = c_idx
            elif "paper id" in cl:
                col_map["paper_id"] = c_idx
            elif any(k in cl for k in ["class", "lớp", "moodle shell"]):
                col_map["class"] = c_idx

        if "name" in col_map or "id" in col_map:
            header_row_idx = r_idx
            break

    if header_row_idx == -1:
        return

    stt_counter = 1
    for r_idx in range(header_row_idx + 1, len(rows)):
        row = rows[r_idx]
        if not any(row):
            continue

        def get_col(k: str) -> str:
            idx = col_map.get(k, -1)
            if idx != -1 and idx < len(row):
                return row[idx]
            return ""

        s_id = _clean_id_str(get_col("id"))
        s_name = get_col("name").strip()
        paper_id = _clean_id_str(get_col("paper_id"))
        class_code = get_col("class").strip()

        if not (s_id or s_name):
            continue

        student = FormStudentItem(
            stt=stt_counter,
            greenwich_id=s_id if s_id.isdigit() else "",
            fpt_id=s_id if not s_id.isdigit() else "",
            full_name=s_name,
            paper_id=paper_id,
            class_code=class_code,
            has_paper_id=bool(paper_id)
        )
        sheet_data.students.append(student)
        stt_counter += 1
