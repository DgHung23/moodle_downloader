import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests
from lxml import html as lh

# Thiết lập encoding UTF-8 cho console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import MOODLE_BASE_URL, REQUEST_DELAY, REQUEST_TIMEOUT, SUBMISSIONS_OUTPUT_DIR
from downloader import sanitize_filesystem_name, format_course_folder_name


from datetime import datetime


def parse_moodle_date(date_str: str) -> Dict[str, Any]:
    """Phân tích ngày tháng Moodle Turnitin thành ISO và tính số ngày còn lại"""
    if not date_str:
        return {"parsed": False, "iso": "", "days_left": None, "status": "unknown", "badge_text": ""}

    m = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})(?:\s*-\s*(\d{1,2}:\d{2}))?', date_str)
    if not m:
        return {"parsed": False, "iso": "", "days_left": None, "status": "unknown", "badge_text": ""}

    day = int(m.group(1))
    month_name = m.group(2).lower()
    year = int(m.group(3))
    time_str = m.group(4) or "23:59"

    months = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12
    }
    month = months.get(month_name[:3], 1)
    hour, minute = [int(x) for x in time_str.split(":")]

    try:
        dt = datetime(year, month, day, hour, minute)
        now = datetime.now()
        diff = dt - now
        days_left = diff.days

        if days_left < 0:
            status = "closed"
            badge_text = f"Đã kết thúc ({abs(days_left)} ngày trước)"
        elif days_left <= 7:
            status = "urgent"
            badge_text = f"Gấp: Còn {days_left} ngày"
        elif days_left <= 30:
            status = "upcoming"
            badge_text = f"Sắp tới hạn: Còn {days_left} ngày"
        else:
            status = "open"
            badge_text = f"Còn {days_left} ngày"

        return {
            "parsed": True,
            "iso": dt.strftime("%Y-%m-%d %H:%M"),
            "days_left": days_left,
            "status": status,
            "badge_text": badge_text
        }
    except Exception:
        return {"parsed": False, "iso": "", "days_left": None, "status": "unknown", "badge_text": ""}


@dataclass
class SubmissionPart:
    """Mô tả một Part trong Turnitin Assignment"""
    part_id: str
    part_name: str
    start_date: str = ""
    due_date: str = ""
    post_date: str = ""
    max_marks: str = "100"
    total_enrolled: int = 0
    submitted_count: int = 0
    due_date_iso: str = ""
    days_left: Optional[int] = None
    deadline_status: str = "unknown"
    deadline_badge: str = ""


@dataclass
class TurnitinDrop:
    """Mô tả một đợt nộp bài Coursework (Turnitin Assignment 2)"""
    cm_id: str
    title: str
    url: str
    section_name: str = "Coursework Submission"
    assignment_id: str = ""
    sesskey: str = ""
    parts: List[SubmissionPart] = field(default_factory=list)
    primary_due_date: str = ""
    primary_due_iso: str = ""
    days_left: Optional[int] = None
    deadline_status: str = "unknown"
    deadline_badge: str = ""


@dataclass
class StudentSubmissionItem:
    """Mô tả một bài nộp của sinh viên"""
    student_id: str             # Moodle User ID
    student_name: str           # Họ và tên sinh viên
    student_profile_url: str    # Link profile sinh viên
    paper_id: str               # Turnitin Paper ID
    submission_title: str       # Tiêu đề bài nộp
    submitted_at: str           # Thời gian nộp (VD: 2/12/25, 07:31)
    similarity_score: Optional[int] = None  # Điểm tương đồng (%)
    similarity_text: str = ""   # Chuỗi hiển thị (VD: "14%")
    grade: str = ""             # Điểm số (VD: "64" hoặc "--")
    max_grade: str = ""         # Điểm tối đa (VD: "100")
    overall_grade: str = ""     # Điểm tổng kết
    has_submission: bool = False
    download_id: str = ""       # ID dùng để gọi download
    raw_row: List[Any] = field(default_factory=list)


class TurnitinSubmissionCrawler:
    """
    Crawler chuyên biệt phục vụ quét đợt nộp Coursework Turnitin và tải bài nộp của sinh viên
    dành cho Giảng viên (Instructor).
    """
    def __init__(self, session: requests.Session):
        self.session = session

    def _safe_get(self, url: str, retries: int = 4, backoff: float = 1.5, **kwargs) -> Optional[requests.Response]:
        timeout = kwargs.pop("timeout", 45)
        for attempt in range(1, retries + 1):
            try:
                time.sleep(REQUEST_DELAY)
                res = self.session.get(url, timeout=timeout, **kwargs)
                if res.status_code in [500, 502, 503, 504]:
                    raise requests.HTTPError(f"HTTP status {res.status_code}")
                return res
            except Exception as e:
                if attempt == retries:
                    print(f"[!] Lỗi kết nối sau {retries} lần thử ({url[:60]}): {e}", flush=True)
                    return None
                wait_time = backoff * attempt
                print(f"[!] Mạng chậm ({e}). Đang tự động thử lại GET lần {attempt + 1}/{retries} sau {wait_time:.1f}s...", flush=True)
                time.sleep(wait_time)
        return None

    def _safe_post(self, url: str, data=None, retries: int = 4, backoff: float = 1.5, **kwargs) -> Optional[requests.Response]:
        timeout = kwargs.pop("timeout", 45)
        for attempt in range(1, retries + 1):
            try:
                time.sleep(REQUEST_DELAY)
                res = self.session.post(url, data=data, timeout=timeout, **kwargs)
                if res.status_code in [500, 502, 503, 504]:
                    raise requests.HTTPError(f"HTTP status {res.status_code}")
                return res
            except Exception as e:
                if attempt == retries:
                    print(f"[!] Lỗi kết nối POST sau {retries} lần thử ({url[:60]}): {e}", flush=True)
                    return None
                wait_time = backoff * attempt
                print(f"[!] Mạng chậm ({e}). Đang tự động thử lại POST lần {attempt + 1}/{retries} sau {wait_time:.1f}s...", flush=True)
                time.sleep(wait_time)
        return None

    def verify_lecturer_role(self) -> Dict[str, Any]:
        """
        Kiểm tra xem phiên đăng nhập hiện tại có quyền Giảng viên (Instructor) hay không.
        Trả về dictionary: { "is_lecturer": bool, "user_name": str, "user_id": str, "message": str }
        """
        home_res = self._safe_get(MOODLE_BASE_URL)
        if not home_res:
            return {"is_lecturer": False, "message": "Không thể kết nối tới Moodle Home."}

        tree = lh.fromstring(home_res.content)
        user_name_nodes = tree.xpath('//span[contains(@class, "usertext")]//text() | //div[contains(@class, "usermenu")]//span[contains(@class, "userbutton")]//text()')
        user_name = " ".join("".join(user_name_nodes).split()).strip()

        # Tìm user ID từ link user/view.php hoặc user/profile.php
        user_id = ""
        user_links = tree.xpath('//a[contains(@href, "/user/profile.php") or contains(@href, "/user/view.php")]/@href')
        for l in user_links:
            m = re.search(r'id=(\d+)', l)
            if m:
                user_id = m.group(1)
                break

        # Quét nhanh 1 khóa học đầu tiên để xác định quyền switchrole hoặc editmode
        course_links = tree.xpath('//a[contains(@href, "course/view.php?id=")]/@href')
        is_lecturer = False
        sample_course_id = ""

        for c_href in course_links[:3]:
            m = re.search(r'id=(\d+)', c_href)
            if m and m.group(1) != "1":
                sample_course_id = m.group(1)
                break

        if sample_course_id:
            c_res = self._safe_get(f"{MOODLE_BASE_URL}/course/view.php?id={sample_course_id}")
            if c_res:
                c_tree = lh.fromstring(c_res.content)
                # Dấu hiệu nhận biết Giảng viên: switchrole.php, setmode (editmode), hoặc quản lý course
                has_switchrole = bool(c_tree.xpath('//a[contains(@href, "switchrole.php")]'))
                has_editmode = bool(c_tree.xpath('//*[contains(@class, "editmode") or contains(@name, "setmode")]'))
                if has_switchrole or has_editmode:
                    is_lecturer = True

        return {
            "is_lecturer": is_lecturer,
            "user_name": user_name or "Giảng viên Greenwich",
            "user_id": user_id,
            "sample_course_id": sample_course_id,
            "message": "Xác nhận quyền Giảng viên (Instructor) thành công!" if is_lecturer else "Tài khoản không có quyền Giảng viên."
        }

    def get_course_submission_drops(self, course_id: str) -> List[TurnitinDrop]:
        """
        Quét trang khóa học để tìm tất cả các đợt nộp bài Coursework Turnitin
        (nằm trong section Coursework Submission hoặc bất kỳ section nào).
        """
        course_url = f"{MOODLE_BASE_URL}/course/view.php?id={course_id}"
        res = self._safe_get(course_url)
        if not res:
            return []

        tree = lh.fromstring(res.content)
        sections = tree.xpath('//li[starts-with(@id, "section-")] | //*[contains(@class, "section") and starts-with(@id, "section-")]')

        drops: List[TurnitinDrop] = []
        seen_cm_ids = set()

        for s_node in sections:
            s_title_nodes = s_node.xpath(
                './/*[contains(@class, "sectionname")]//text() | '
                './/h3[contains(@class, "section-title")]//text() | '
                './/*[contains(@class, "section-title")]//text()'
            )
            s_title = " ".join("".join(s_title_nodes).split()).strip() or "General"

            tii_links = s_node.xpath('.//a[contains(@href, "/mod/turnitintooltwo/view.php?id=")]')
            for a in tii_links:
                href = a.attrib.get("href", "")
                m = re.search(r'id=(\d+)', href)
                if not m:
                    continue
                cm_id = m.group(1)
                if cm_id in seen_cm_ids:
                    continue
                seen_cm_ids.add(cm_id)

                title_nodes = a.xpath('.//*[contains(@class, "instancename")]/text()')
                title = title_nodes[0].strip() if title_nodes else " ".join(a.text_content().split())
                # Làm sạch đuôi "Turnitin Assignment 2"
                title = re.sub(r'\s*Turnitin Assignment\s*\d*\s*$', '', title, flags=re.IGNORECASE).strip()

                drop = TurnitinDrop(
                    cm_id=cm_id,
                    title=title or f"Coursework Drop {cm_id}",
                    url=f"{MOODLE_BASE_URL}/mod/turnitintooltwo/view.php?id={cm_id}",
                    section_name=s_title
                )
                drops.append(drop)

        return drops

    def get_drop_details(self, cm_id: str) -> Optional[TurnitinDrop]:
        """
        Lấy thông tin chi tiết một đợt nộp Turnitin: assignment_id, sesskey, các Parts và hạn nộp.
        """
        drop_url = f"{MOODLE_BASE_URL}/mod/turnitintooltwo/view.php?id={cm_id}"
        res = self._safe_get(drop_url)
        if not res:
            return None

        tree = lh.fromstring(res.content)
        sesskey_m = re.search(r'"sesskey":"([^"]+)"', res.text)
        sesskey = sesskey_m.group(1) if sesskey_m else ""

        assignment_id_el = tree.xpath('//*[@id="assignment_id"]/text()')
        assignment_id = assignment_id_el[0].strip() if assignment_id_el else ""

        # Tiêu đề đợt nộp
        first_h2 = tree.xpath('//h2[contains(@class, "main")] | //h2')
        if first_h2:
            page_title = " ".join("".join(first_h2[0].xpath('.//text()')).split()).strip()
        else:
            page_title = ""
        # Loại bỏ các prefix/suffix không cần thiết
        page_title = re.sub(r'^Blocks', '', page_title).strip()
        page_title = re.sub(r'Part\s*\d+.*$', '', page_title).strip()

        drop = TurnitinDrop(
            cm_id=cm_id,
            title=page_title,
            url=drop_url,
            assignment_id=assignment_id,
            sesskey=sesskey,
            parts=[]
        )

        # Lấy thông tin các Parts từ bảng mod_turnitintooltwo_part_details và các tab
        part_tabs = tree.xpath('//div[starts-with(@id, "tabs-")]')
        part_details_tables = tree.xpath('//table[contains(@class, "mod_turnitintooltwo_part_details")]')

        for idx, pt in enumerate(part_tabs):
            pid = pt.attrib.get("id", "").replace("tabs-", "").strip()
            if not pid:
                continue

            # Tên part từ tab header
            title_el = tree.xpath(f'//a[@href="#tabs-{pid}"]/text()')
            part_name = title_el[0].strip() if title_el else f"Part {idx + 1}"

            # Đọc ngày tháng từ bảng details tương ứng
            start_date, due_date, post_date, max_marks = "", "", "", "100"
            if idx < len(part_details_tables):
                tbl = part_details_tables[idx]
                rows = tbl.xpath('.//tr')
                if len(rows) >= 2:
                    cells = [ " ".join(c.text_content().split()).strip() for c in rows[1].xpath('.//td | .//th') ]
                    # Cấu trúc: [Title, Start Date, Due Date, Post Date, Marks Available, Export]
                    if len(cells) >= 5:
                        start_date = cells[1]
                        due_date = cells[2]
                        post_date = cells[3]
                        max_marks = cells[4]

            part = SubmissionPart(
                part_id=pid,
                part_name=part_name,
                start_date=start_date,
                due_date=due_date,
                post_date=post_date,
                max_marks=max_marks
            )

            # Phân tích hạn nộp
            parsed_due = parse_moodle_date(due_date)
            if not parsed_due["parsed"] and page_title:
                parsed_due = parse_moodle_date(page_title)

            if parsed_due["parsed"]:
                part.due_date_iso = parsed_due["iso"]
                part.days_left = parsed_due["days_left"]
                part.deadline_status = parsed_due["status"]
                part.deadline_badge = parsed_due["badge_text"]

            drop.parts.append(part)

        # Thiết lập deadline chính của đợt nộp dựa trên Part 1 hoặc title
        if drop.parts and drop.parts[0].due_date_iso:
            drop.primary_due_date = drop.parts[0].due_date
            drop.primary_due_iso = drop.parts[0].due_date_iso
            drop.days_left = drop.parts[0].days_left
            drop.deadline_status = drop.parts[0].deadline_status
            drop.deadline_badge = drop.parts[0].deadline_badge
        else:
            parsed_title_due = parse_moodle_date(page_title)
            if parsed_title_due["parsed"]:
                drop.primary_due_date = parsed_title_due["formatted"]
                drop.primary_due_iso = parsed_title_due["iso"]
                drop.days_left = parsed_title_due["days_left"]
                drop.deadline_status = parsed_title_due["status"]
                drop.deadline_badge = parsed_title_due["badge_text"]

        return drop

    def get_part_submissions(self, drop_url: str, assignment_id: str, part_id: str, sesskey: str) -> List[StudentSubmissionItem]:
        """
        Gọi API ajax.php để lấy danh sách sinh viên và bài nộp trong 1 Part cụ thể.
        Tự động phân trang nếu số lượng sinh viên > 100.
        """
        ajax_url = f"{MOODLE_BASE_URL}/mod/turnitintooltwo/ajax.php"
        headers = {
            "Referer": drop_url,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }

        all_items: List[StudentSubmissionItem] = []
        start = 0
        total = 0

        while True:
            payload = {
                "action": "get_submissions",
                "assignment": assignment_id,
                "part": part_id,
                "start": str(start),
                "refresh_requested": "0",
                "sesskey": sesskey,
                "total": str(total)
            }

            res = self._safe_post(ajax_url, data=payload, headers=headers)
            if not res or res.status_code != 200:
                print(f"[!] Lỗi khi gọi get_submissions cho part {part_id}", flush=True)
                break

            try:
                data = res.json()
            except Exception as e:
                print(f"[!] Lỗi parse JSON get_submissions: {e}", flush=True)
                break

            aa_data = data.get("aaData", [])
            total = int(data.get("total", len(aa_data)))
            end = int(data.get("end", start + len(aa_data)))

            for row in aa_data:
                item = self._parse_submission_row(row, part_id)
                all_items.append(item)

            if end >= total or not aa_data or end == start:
                break
            start = end

        return all_items

    def _parse_submission_row(self, row: List[Any], part_id: str) -> StudentSubmissionItem:
        """
        Bóc tách 1 hàng dữ liệu từ mảng aaData của Turnitin thành StudentSubmissionItem
        """
        # Col 0: part_id
        # Col 1: checkbox (value=submission_id)
        # Col 2: Last Name
        # Col 3: Student link HTML: <a href=".../user/view.php?id=231022&course=121957">Nguyen Bao</a>
        # Col 4: Submission Title plain text
        # Col 5: Submission Title HTML
        # Col 6: Turnitin Paper ID (VD: 269297864)
        # Col 7: Timestamp
        # Col 8: Submitted Date (VD: 2/12/25, 07:31)
        # Col 9: Similarity numeric score (VD: 14 hoặc None)
        # Col 10: Similarity HTML
        # Col 11: Grade numeric (VD: 64 hoặc None)
        # Col 12: Grade HTML
        # Col 13: Overall Grade HTML
        # Col 16: Download original HTML (<div id="downloadoriginal_269297864_115275_231022" class="download_original_open">)
        # Col 19: First Name

        student_name = ""
        student_id = ""
        student_url = ""

        # Bóc tách tên và profile url từ Col 3
        col3_str = str(row[3]) if len(row) > 3 else ""
        if "<a" in col3_str:
            try:
                tree = lh.fromstring(col3_str)
                a_tags = tree.xpath('//a')
                if a_tags:
                    student_name = a_tags[0].text_content().strip()
                    student_url = a_tags[0].attrib.get("href", "")
                    m_uid = re.search(r'id=(\d+)', student_url)
                    if m_uid:
                        student_id = m_uid.group(1)
            except Exception:
                student_name = re.sub(r'<[^>]+>', '', col3_str).strip()
        else:
            student_name = col3_str.strip()

        if not student_name and len(row) > 19 and len(row) > 2:
            first_name = str(row[19]).strip() if row[19] else ""
            last_name = str(row[2]).strip() if row[2] else ""
            student_name = f"{first_name} {last_name}".strip()

        # Submission Title
        sub_title = str(row[4]).strip() if len(row) > 4 and row[4] else ""
        if not sub_title and len(row) > 5:
            sub_title = re.sub(r'<[^>]+>', '', str(row[5])).strip()

        # Paper ID
        raw_paper_id = str(row[6]).strip() if len(row) > 6 and row[6] is not None else ""
        paper_id = raw_paper_id if (raw_paper_id.isdigit() and raw_paper_id != "0") else ""

        # Download ID
        download_id = ""
        if len(row) > 16 and row[16]:
            m_dl = re.search(r'downloadoriginal_([0-9]+)_', str(row[16]))
            if m_dl:
                download_id = m_dl.group(1)

        if not paper_id and download_id:
            paper_id = download_id

        has_submission = bool(paper_id and paper_id.isdigit())

        # Clean title
        if sub_title in ["--", "-", "None", "null"]:
            sub_title = "Coursework" if has_submission else ""

        # Submitted at
        submitted_at = str(row[8]).strip() if len(row) > 8 and row[8] else ""
        if submitted_at in ["--", "-", "None", "null"]:
            submitted_at = ""

        # Similarity Score
        sim_score: Optional[int] = None
        sim_text = ""
        if has_submission:
            if len(row) > 9 and row[9] is not None:
                try:
                    sim_score = int(row[9])
                    sim_text = f"{sim_score}%"
                except (ValueError, TypeError):
                    pass
            if not sim_text and len(row) > 10 and row[10]:
                raw_sim = re.sub(r'<[^>]+>', '', str(row[10])).strip()
                if raw_sim and raw_sim not in ["--", "-"]:
                    sim_text = raw_sim
                    m_sim = re.search(r'(\d+)', raw_sim)
                    if m_sim:
                        sim_score = int(m_sim.group(1))

        # Grade
        grade = ""
        if has_submission:
            if len(row) > 11 and row[11] is not None:
                grade = str(row[11]).strip()
            if not grade and len(row) > 12 and row[12]:
                m_g = re.search(r'class="grade">([^<]+)<', str(row[12]))
                if m_g:
                    grade = m_g.group(1).strip()
            if grade in ["--", "-"]:
                grade = ""

        max_grade = "100"
        if len(row) > 12 and row[12]:
            m_mg = re.search(r'class="grademark_grade">/([^<]+)<', str(row[12]))
            if m_mg:
                max_grade = m_mg.group(1).strip()

        # Overall Grade
        overall_grade = ""
        if len(row) > 13 and row[13]:
            overall_grade = re.sub(r'<[^>]+>', '', str(row[13])).strip()

        # Download ID
        download_id = paper_id
        if len(row) > 16 and row[16]:
            m_dl = re.search(r'downloadoriginal_([0-9]+)_', str(row[16]))
            if m_dl:
                download_id = m_dl.group(1)

        return StudentSubmissionItem(
            student_id=student_id,
            student_name=student_name,
            student_profile_url=student_url,
            paper_id=paper_id,
            submission_title=sub_title or "Submission",
            submitted_at=submitted_at,
            similarity_score=sim_score,
            similarity_text=sim_text or ("Chưa có" if has_submission else ""),
            grade=grade,
            max_grade=max_grade,
            overall_grade=overall_grade,
            has_submission=has_submission,
            download_id=download_id,
            raw_row=row
        )

    def download_single_submission(
        self,
        drop_url: str,
        assignment_id: str,
        submission_id: str,
        save_folder: Path,
        suggested_prefix: str = ""
    ) -> Optional[Path]:
        """
        Tải file bài nộp nguyên bản của sinh viên thông qua LTI:
        1. Gọi ajax.php với action="downloadoriginal"
        2. Bóc tách form LTI có chữ ký OAuth
        3. POST form LTI tới Turnitin và lưu file
        """
        ajax_url = f"{MOODLE_BASE_URL}/mod/turnitintooltwo/ajax.php"
        headers = {
            "Referer": drop_url,
            "X-Requested-With": "XMLHttpRequest",
        }
        payload = {
            "action": "downloadoriginal",
            "submission": submission_id,
            "assignment": assignment_id
        }

        res = self._safe_post(ajax_url, data=payload, headers=headers)
        if not res or res.status_code != 200 or not res.text.strip():
            print(f"[!] downloadoriginal trả về rỗng cho submission {submission_id}", flush=True)
            return None

        tree = lh.fromstring(res.content)
        forms = tree.xpath('//form')
        if not forms:
            print(f"[!] Không tìm thấy form LTI trong phản hồi tải cho submission {submission_id}", flush=True)
            return None

        form = forms[0]
        action_url = form.attrib.get('action')
        if not action_url:
            return None

        form_data = {}
        for inp in form.xpath('.//input'):
            name = inp.attrib.get('name')
            val = inp.attrib.get('value', '')
            if name:
                form_data[name] = val

        # POST tới endpoint LTI của Turnitin
        download_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
            "Referer": drop_url,
        }

        dl_res = requests.post(action_url, data=form_data, headers=download_headers, stream=True, timeout=60)
        if dl_res.status_code != 200:
            print(f"[!] LTI download thất bại với HTTP status {dl_res.status_code}", flush=True)
            return None

        # Trích xuất filename từ Content-Disposition
        cd = dl_res.headers.get("Content-Disposition", "")
        raw_filename = ""
        m_fn = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)["\']?', cd, flags=re.IGNORECASE)
        if m_fn:
            raw_filename = urllib.parse.unquote(m_fn.group(1).strip())

        # Nếu không có header, dự đoán extension từ Content-Type
        if not raw_filename:
            ct = dl_res.headers.get("Content-Type", "").lower()
            ext = ".pdf"
            if "zip" in ct:
                ext = ".zip"
            elif "word" in ct or "docx" in ct:
                ext = ".docx"
            elif "powerpoint" in ct or "pptx" in ct:
                ext = ".pptx"
            raw_filename = f"{submission_id}{ext}"

        # Đặt tên file chuẩn mực: [Prefix]_[Tên File Gốc]
        if suggested_prefix:
            clean_prefix = sanitize_filesystem_name(suggested_prefix)
            clean_orig = sanitize_filesystem_name(raw_filename)
            # Nếu prefix đã có trong tên file gốc thì không duplicate
            if clean_prefix in clean_orig:
                final_filename = clean_orig
            else:
                final_filename = f"{clean_prefix}_{clean_orig}"
        else:
            final_filename = sanitize_filesystem_name(raw_filename)

        save_folder.mkdir(parents=True, exist_ok=True)
        target_path = save_folder / final_filename

        # Ghi file theo chunks (requests tự giải nén gzip stream nếu có)
        with open(target_path, "wb") as f:
            for chunk in dl_res.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        return target_path

    def download_part_zip(
        self,
        drop_url: str,
        assignment_id: str,
        part_id: str,
        save_folder: Path,
        zip_filename: str
    ) -> Optional[Path]:
        """
        Tải toàn bộ bài nộp trong 1 Part thành 1 file ZIP chính thức từ Turnitin (action="orig_zip")
        """
        ajax_url = f"{MOODLE_BASE_URL}/mod/turnitintooltwo/ajax.php"
        headers = {
            "Referer": drop_url,
            "X-Requested-With": "XMLHttpRequest",
        }
        payload = {
            "action": "orig_zip",
            "assignment": assignment_id,
            "part": part_id,
            "submission_ids": []
        }

        res = self._safe_post(ajax_url, data=payload, headers=headers)
        if not res or res.status_code != 200 or not res.text.strip():
            return None

        tree = lh.fromstring(res.content)
        forms = tree.xpath('//form')
        if not forms:
            return None

        form = forms[0]
        action_url = form.attrib.get('action')
        if not action_url:
            return None

        form_data = { inp.attrib.get('name'): inp.attrib.get('value', '') for inp in form.xpath('.//input') if inp.attrib.get('name') }

        download_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
            "Referer": drop_url,
        }

        dl_res = requests.post(action_url, data=form_data, headers=download_headers, stream=True, timeout=120)
        if dl_res.status_code != 200:
            return None

        save_folder.mkdir(parents=True, exist_ok=True)
        clean_zip_name = sanitize_filesystem_name(zip_filename)
        if not clean_zip_name.lower().endswith(".zip"):
            clean_zip_name += ".zip"

        target_path = save_folder / clean_zip_name
        with open(target_path, "wb") as f:
            for chunk in dl_res.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        return target_path
