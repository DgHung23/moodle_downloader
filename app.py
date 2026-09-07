import json
import os
import re
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

# Thiết lập encoding UTF-8 cho console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import bottle
from bottle import Bottle, request, response, static_file

from auth import (
    get_authenticated_session,
    get_firefox_profile_path,
    extract_cookies_from_firefox,
    extract_cookies_from_chromium,
)
from config import OUTPUTS_DIR, SUBMISSIONS_OUTPUT_DIR, MOODLE_BASE_URL, DEFAULT_EXTENSIONS
from crawler import MoodleCrawler, MoodleCourse
from downloader import Downloader, format_course_folder_name, sanitize_filesystem_name
from submission_crawler import TurnitinSubmissionCrawler

app = Bottle()
BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

# Global State quản lý tiến trình crawl
class AppState:
    def __init__(self):
        self.session = None
        self.courses: List[Dict] = []
        self.is_downloading = False
        self.current_course_id = None
        self.current_course_name = ""
        self.current_file = ""
        self.total_downloaded = 0
        self.logs: List[Dict] = []
        self.should_stop = False
        self.lock = threading.Lock()

        # Quản lý tải Submissions của giảng viên
        self.is_downloading_submissions = False
        self.should_stop_submissions = False
        self.submissions_current_course = ""
        self.submissions_current_drop = ""
        self.submissions_current_student = ""
        self.submissions_current_file = ""
        self.submissions_total_downloaded = 0
        self.submissions_total_target = 0
        self.submissions_logs: List[Dict] = []
        self.submissions_last_zip_path = ""
        self.submissions_last_zip_name = ""

        # Caching dữ liệu lớn cho Giảng viên (tối ưu hóa tốc độ và giảm tải mạng)
        self.cached_subjects: List[Dict] = []
        self.cached_courses: List[Dict] = []
        self.cached_drops: Dict[str, List[Dict]] = {}

    def add_log(self, message: str, log_type: str = "info"):
        with self.lock:
            timestamp = time.strftime("%H:%M:%S")
            self.logs.append({
                "time": timestamp,
                "text": message,
                "type": log_type
            })
            if len(self.logs) > 300:
                self.logs.pop(0)

    def add_submission_log(self, message: str, log_type: str = "info"):
        with self.lock:
            timestamp = time.strftime("%H:%M:%S")
            self.submissions_logs.append({
                "time": timestamp,
                "text": message,
                "type": log_type
            })
            if len(self.submissions_logs) > 300:
                self.submissions_logs.pop(0)

state = AppState()


# Helper: Tạo session từ cookie do người dùng cung cấp hoặc tự trích xuất
def resolve_session(user_session_id: Optional[str] = None):
    session = requests_session = None
    if user_session_id and user_session_id.strip():
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util import Retry
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=25, pool_maxsize=25)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        session.cookies.set("MoodleSession", user_session_id.strip(), domain="moodlecurrent.gre.ac.uk", path="/")
        # Kiểm tra tính hợp lệ
        res = session.get(MOODLE_BASE_URL, timeout=15)
        if "My modules" in res.text or "course/view.php" in res.text:
            return session, "Đăng nhập thành công bằng MoodleSession đã nhập!"
        else:
            raise ValueError("MoodleSession không hợp lệ hoặc đã hết hạn. Vui lòng kiểm tra lại cookie!")
    else:
        # Tự động từ Firefox / Edge
        session = get_authenticated_session()
        return session, "Tự động đăng nhập thành công thông qua phiên trình duyệt SSO!"


# Routes phục vụ Web UI
@app.route("/")
def index():
    return static_file("index.html", root=str(WEB_DIR))


@app.route("/submissions")
def submissions():
    return static_file("submissions.html", root=str(WEB_DIR))


@app.route("/static/<filepath:path>")
def serve_static(filepath):
    return static_file(filepath, root=str(WEB_DIR))


# API: Tự động trích xuất MoodleSession từ Firefox / Edge / Chrome
@app.route("/api/session/detect", method=["GET", "POST"])
def detect_session():
    try:
        browser = request.query.get("browser", "firefox").lower()
        if request.json and "browser" in request.json:
            browser = request.json["browser"].lower()

        if browser == "firefox":
            profile_path = get_firefox_profile_path()
            if not profile_path:
                return {"status": "error", "message": "Không tìm thấy Firefox Profile nào trên máy!"}

            cookies = extract_cookies_from_firefox(profile_path)
            moodle_session = next((c["value"] for c in cookies if c["name"] == "MoodleSession"), "")
            return {
                "status": "ok",
                "browser": "firefox",
                "detected": bool(moodle_session or cookies),
                "profile": profile_path.name,
                "moodle_session": moodle_session,
                "message": f"Đã tìm thấy phiên đăng nhập trong Firefox ({profile_path.name})!"
            }
        elif browser in ["edge", "chrome"]:
            display_name = "Microsoft Edge" if browser == "edge" else "Google Chrome"
            cookies, msg = extract_cookies_from_chromium(browser)
            moodle_session = next((c["value"] for c in cookies if c["name"] == "MoodleSession"), "")
            if moodle_session or cookies:
                return {
                    "status": "ok",
                    "browser": browser,
                    "detected": True,
                    "profile": "Default",
                    "moodle_session": moodle_session,
                    "message": f"Đã trích xuất thành công MoodleSession từ {display_name}!"
                }
            else:
                return {"status": "error", "browser": browser, "message": msg}
        else:
            return {"status": "error", "message": f"Trình duyệt '{browser}' không được hỗ trợ."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# API: Fetch danh sách các môn học
@app.route("/api/courses/fetch", method="POST")
def fetch_courses():
    try:
        data = request.json or {}
        manual_session = data.get("session_id", "").strip()

        session, msg = resolve_session(manual_session)
        state.session = session
        state.add_log(msg, "success")

        crawler = MoodleCrawler(session=session)
        raw_courses = crawler.get_enrolled_courses()

        course_list = []
        outputs_path = Path(OUTPUTS_DIR)

        for c in raw_courses:
            clean_name = format_course_folder_name(c.name)
            folder_name = sanitize_filesystem_name(clean_name)
            course_dir = outputs_path / folder_name
            
            # Đếm số file đã tải trong folder này nếu có
            downloaded_files = 0
            if course_dir.exists():
                downloaded_files = len(list(course_dir.glob("**/*.*")))

            # Tách mã môn và tên môn
            code_match = re.match(r"^([A-Z0-9-]+)\s*-\s*(.*)$", clean_name)
            if code_match:
                code = code_match.group(1)
                title = code_match.group(2)
            else:
                code = c.id
                title = clean_name

            # Trích xuất mã lớp (M01, M02,...) và năm học nếu có
            class_match = re.search(r"-(M\d+)-(\d{4}-\d{2})", c.name, flags=re.IGNORECASE)
            if class_match:
                class_code = class_match.group(1).upper()
                academic_year = class_match.group(2)
            else:
                m_match = re.search(r"-(M\d+)", c.name, flags=re.IGNORECASE)
                class_code = m_match.group(1).upper() if m_match else ""
                y_match = re.search(r"(\d{4}-\d{2})", c.name)
                academic_year = y_match.group(1) if y_match else ""

            course_list.append({
                "id": c.id,
                "name": clean_name,
                "code": code,
                "title": title,
                "subject_key": clean_name,
                "class_code": class_code,
                "academic_year": academic_year,
                "raw_name": c.name,
                "url": c.url,
                "folder_name": folder_name,
                "downloaded_files": downloaded_files,
                "has_folder": course_dir.exists()
            })

        state.courses = course_list
        state.add_log(f"Đã tải thành công danh sách {len(course_list)} môn học!", "success")

        return {
            "status": "ok",
            "courses": course_list,
            "total": len(course_list)
        }
    except Exception as e:
        state.add_log(f"Lỗi khi quét danh sách môn: {e}", "error")
        return {"status": "error", "message": str(e)}


def group_courses_by_subject(courses: List[Dict]) -> List[Dict]:
    """
    Gộp các lớp học thành các môn học duy nhất (Subject-centric).
    Mỗi phần tử đại diện cho 1 môn học với đầy đủ các lớp của nó.
    """
    groups_dict = {}
    for c in courses:
        key = c.get("subject_key") or c.get("name") or format_course_folder_name(c.get("raw_name", ""))
        if key not in groups_dict:
            groups_dict[key] = {
                "id": c.get("id"),
                "name": c.get("name") or key,
                "code": c.get("code", ""),
                "title": c.get("title", key),
                "folder_name": c.get("folder_name") or sanitize_filesystem_name(key),
                "subject_key": key,
                "classes": []
            }
        groups_dict[key]["classes"].append(c)
    return list(groups_dict.values())


# Background Worker tải danh sách môn
def download_worker(target_courses: List[Dict], session, is_already_grouped: bool = False):
    state.is_downloading = True
    state.should_stop = False
    crawler = MoodleCrawler(session=session)
    downloader = Downloader(session=session, output_dir=Path(OUTPUTS_DIR))

    # Tự động gộp theo môn học để xử lý trọn vẹn từng môn
    subjects = target_courses if is_already_grouped else group_courses_by_subject(target_courses)
    total_classes = sum(len(s.get("classes", [s])) for s in subjects)

    state.add_log(f"Bắt đầu tiến trình tải cho {len(subjects)} môn học (tổng hợp từ {total_classes} lớp học)...", "info")

    try:
        for s_idx, subj in enumerate(subjects, 1):
            if state.should_stop:
                state.add_log("Tiến trình tải đã bị hủy bởi người dùng.", "warning")
                break

            subj_name = subj["name"]
            folder_name = subj.get("folder_name") or sanitize_filesystem_name(subj_name)
            classes = subj.get("classes") or [subj]

            state.current_course_id = classes[0]["id"]
            state.current_course_name = subj_name

            class_labels = [c.get("class_code") or f"ID:{c['id']}" for c in classes[:4]]
            class_str = ", ".join(class_labels)
            if len(classes) > 4:
                class_str += f", +{len(classes)-4} lớp khác"

            state.add_log(f"[{s_idx}/{len(subjects)}] 📚 Bắt đầu môn: {subj_name} (Gộp {len(classes)} lớp: {class_str})", "info")

            subj_downloaded_count = 0
            # Duyệt qua từng lớp của môn học này để gom toàn bộ sections và files
            for c_idx, c_info in enumerate(classes, 1):
                if state.should_stop:
                    break

                moodle_course = MoodleCourse(
                    id=c_info["id"],
                    name=c_info["raw_name"],
                    url=c_info["url"]
                )

                try:
                    sections = crawler.get_course_sections(moodle_course)
                    for s in sections:
                        if state.should_stop:
                            break
                        if not s.items:
                            continue

                        for raw_item in s.items:
                            if state.should_stop:
                                break
                            resolved = crawler.resolve_resource_file(raw_item)
                            for dl_url, suggested_title, subfolder_name in resolved:
                                if state.should_stop:
                                    break
                                state.current_file = suggested_title
                                out_p = downloader.download_file(
                                    course=moodle_course,
                                    section=s,
                                    download_url=dl_url,
                                    suggested_title=suggested_title,
                                    folder_name=subfolder_name,
                                    course_folder_name=folder_name
                                )
                                if out_p:
                                    subj_downloaded_count += 1
                                    state.total_downloaded += 1
                                    state.add_log(f"Tải thành công: {out_p.name}", "success")
                except Exception as e:
                    state.add_log(f"Lỗi khi xử lý lớp {c_info.get('class_code') or c_info['id']} ({subj_name}): {e}", "error")

            state.add_log(f"✅ Hoàn tất môn [{s_idx}/{len(subjects)}]: {subj_name} (Đã xử lý {subj_downloaded_count} files)", "success")

        state.add_log(f"🎉 Hoàn tất toàn bộ {len(subjects)} môn học! Tổng cộng đã xử lý {state.total_downloaded} files.", "success")
    finally:
        state.is_downloading = False
        state.current_course_id = None
        state.current_course_name = ""
        state.current_file = ""


# API: Tải 1 môn cụ thể (hoặc gộp các lớp của 1 môn)
@app.route("/api/course/download", method="POST")
def download_single_course():
    if state.is_downloading:
        return {"status": "error", "message": "Một tiến trình tải khác đang chạy. Vui lòng chờ hoặc hủy trước!"}

    data = request.json or {}
    course_id = str(data.get("course_id", "")).strip()
    course_ids = data.get("course_ids", [])
    if isinstance(course_ids, str):
        course_ids = [x.strip() for x in course_ids.split(",") if x.strip()]
    elif not isinstance(course_ids, list):
        course_ids = []

    if course_id and not course_ids:
        course_ids = [course_id]

    target_courses = []
    for cid in course_ids:
        for c in state.courses:
            if str(c["id"]) == str(cid) and c not in target_courses:
                target_courses.append(c)
                break

    if not target_courses:
        return {"status": "error", "message": "Không tìm thấy môn học hợp lệ nào để tải!"}

    if not state.session:
        return {"status": "error", "message": "Chưa xác thực phiên Moodle. Vui lòng nhấn Fetch môn học trước!"}

    t = threading.Thread(target=download_worker, args=(target_courses, state.session), daemon=True)
    t.start()

    if len(target_courses) == 1:
        msg = f"Bắt đầu tải môn: {target_courses[0]['name']}"
    else:
        msg = f"Bắt đầu tải gộp {len(target_courses)} lớp của môn: {target_courses[0]['name']}"
    return {"status": "ok", "message": msg}


# API: Tải toàn bộ tất cả các môn
@app.route("/api/courses/download-all", method="POST")
def download_all_courses():
    if state.is_downloading:
        return {"status": "error", "message": "Một tiến trình tải khác đang chạy!"}

    if not state.courses:
        return {"status": "error", "message": "Danh sách môn học đang trống. Vui lòng fetch danh sách môn trước!"}

    if not state.session:
        return {"status": "error", "message": "Chưa xác thực phiên Moodle. Vui lòng nhấn Fetch môn học trước!"}

    data = request.json or {}
    target_ids = data.get("course_ids", [])
    if target_ids:
        target_ids_set = {str(i) for i in target_ids}
        targets = [c for c in state.courses if str(c["id"]) in target_ids_set]
    else:
        targets = list(state.courses)

    if not targets:
        return {"status": "error", "message": "Không có môn học nào được chọn để tải!"}

    t = threading.Thread(target=download_worker, args=(targets, state.session), daemon=True)
    t.start()

    subjects_count = len(group_courses_by_subject(targets))
    return {"status": "ok", "message": f"Bắt đầu tải {subjects_count} môn học (tổng hợp từ {len(targets)} lớp)!"}


# API: Hủy tải
@app.route("/api/download/cancel", method="POST")
def cancel_download():
    if state.is_downloading:
        state.should_stop = True
        state.add_log("Đã gửi yêu cầu dừng tải...", "warning")
        return {"status": "ok", "message": "Đang dừng tải..."}
    return {"status": "ok", "message": "Không có tiến trình nào đang chạy."}


# API: Mở thư mục outputs trong Windows Explorer
@app.route("/api/open-folder", method="POST")
def open_folder():
    data = request.json or {}
    folder_name = data.get("folder_name", "")
    target_path = Path(OUTPUTS_DIR)
    if folder_name:
        target_path = target_path / folder_name

    target_path.mkdir(parents=True, exist_ok=True)

    try:
        if sys.platform == "win32":
            os.startfile(str(target_path.resolve()))
        elif sys.platform == "darwin":
            os.system(f'open "{target_path.resolve()}"')
        else:
            os.system(f'xdg-open "{target_path.resolve()}"')
        return {"status": "ok", "path": str(target_path.resolve())}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# API: Lấy trạng thái hiện tại (polling realtime)
@app.route("/api/status", method="GET")
def get_status():
    # Thống kê tổng số file trong thư mục outputs
    outputs_path = Path(OUTPUTS_DIR)
    total_files_on_disk = 0
    total_size_bytes = 0
    if outputs_path.exists():
        for f in outputs_path.glob("**/*.*"):
            if f.is_file() and not f.name.endswith(".part"):
                total_files_on_disk += 1
                try:
                    total_size_bytes += f.stat().st_size
                except Exception:
                    pass

    return {
        "is_downloading": state.is_downloading,
        "current_course_id": state.current_course_id,
        "current_course_name": state.current_course_name,
        "current_file": state.current_file,
        "total_downloaded": state.total_downloaded,
        "total_files_on_disk": total_files_on_disk,
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
        "logs": state.logs[-60:],  # 60 logs gần nhất
    }


# ==============================================================================
# SUBMISSIONS API (DÀNH CHO GIẢNG VIÊN - TURNITIN COURSEWORK)
# ==============================================================================

# Background worker tải loạt bài nộp của sinh viên
def submission_download_worker(
    session,
    course_name: str,
    drop_title: str,
    drop_url: str,
    assignment_id: str,
    part_name: str,
    target_submissions: List[Dict]
):
    state.is_downloading_submissions = True
    state.should_stop_submissions = False
    state.submissions_current_course = course_name
    state.submissions_current_drop = drop_title
    state.submissions_total_downloaded = 0
    state.submissions_total_target = len(target_submissions)

    clean_course_folder = sanitize_filesystem_name(format_course_folder_name(course_name))
    clean_drop_folder = sanitize_filesystem_name(drop_title)
    clean_part_folder = sanitize_filesystem_name(part_name)

    target_dir = Path(SUBMISSIONS_OUTPUT_DIR) / clean_course_folder / clean_drop_folder / clean_part_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    crawler = TurnitinSubmissionCrawler(session=session)
    state.add_submission_log(f"🚀 Bắt đầu tải {len(target_submissions)} bài nộp vào thư mục: {clean_part_folder}", "info")

    try:
        for idx, sub in enumerate(target_submissions, 1):
            if state.should_stop_submissions:
                state.add_submission_log("⚠️ Tiến trình tải bài nộp đã bị dừng bởi người dùng.", "warning")
                break

            student_name = sub.get("student_name") or f"Student_{idx}"
            student_id = sub.get("student_id", "")
            paper_id = sub.get("paper_id") or sub.get("download_id", "")
            sub_title = sub.get("submission_title", "Coursework")

            if not paper_id or str(paper_id).strip() in ["0", "", "None"]:
                continue

            state.submissions_current_student = student_name
            state.submissions_current_file = f"{student_name} - {sub_title}"

            prefix = f"{student_id}_{student_name}_{sub_title}" if student_id else f"{student_name}_{sub_title}"
            state.add_submission_log(f"[{idx}/{len(target_submissions)}] Đang tải bài nộp: {student_name} (Paper: {paper_id})...", "info")

            saved_path = crawler.download_single_submission(
                drop_url=drop_url,
                assignment_id=assignment_id,
                submission_id=str(paper_id),
                save_folder=target_dir,
                suggested_prefix=prefix
            )

            if saved_path and saved_path.exists():
                state.submissions_total_downloaded += 1
                state.add_submission_log(f"✅ Đã lưu: {saved_path.name}", "success")
            else:
                state.add_submission_log(f"❌ Không thể tải bài nộp của: {student_name} (Paper: {paper_id})", "error")

        # Đóng gói tự động thành file ZIP để tiện tải về máy
        try:
            import shutil
            zip_base_name = f"{clean_course_folder}_{clean_drop_folder}_{clean_part_folder}"
            zip_base_path = target_dir.parent / zip_base_name
            zip_archive_path = shutil.make_archive(str(zip_base_path), 'zip', str(target_dir))
            state.submissions_last_zip_path = zip_archive_path
            state.submissions_last_zip_name = Path(zip_archive_path).name
            state.add_submission_log(f"📦 Đã tạo sẵn file ZIP nén toàn bộ: {state.submissions_last_zip_name}", "success")
        except Exception as z_err:
            print(f"Lỗi nén ZIP sau khi tải: {z_err}")

        state.add_submission_log(f"🎉 Hoàn tất đợt tải! Đã lưu {state.submissions_total_downloaded}/{len(target_submissions)} files vào: {target_dir.name}", "success")
    except Exception as e:
        state.add_submission_log(f"Lỗi trong quá trình tải loạt bài nộp: {e}", "error")
    finally:
        state.is_downloading_submissions = False
        state.submissions_current_student = ""
        state.submissions_current_file = ""


# API: Xác thực quyền Giảng viên
@app.route("/api/submissions/verify", method="POST")
def submissions_verify():
    try:
        data = request.json or {}
        manual_session = data.get("session_id", "").strip()

        session, msg = resolve_session(manual_session)
        state.session = session

        crawler = TurnitinSubmissionCrawler(session=session)
        verify_res = crawler.verify_lecturer_role()

        return {
            "status": "ok",
            "is_lecturer": verify_res.get("is_lecturer", False),
            "user_name": verify_res.get("user_name", ""),
            "user_id": verify_res.get("user_id", ""),
            "message": verify_res.get("message", "")
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# API: Lấy danh sách Môn học đã gộp lớp (Subject-Centric) dành cho Giảng viên
@app.route("/api/submissions/subjects", method="POST")
def get_submission_subjects():
    try:
        data = request.json or {}
        manual_session = data.get("session_id", "").strip()
        force_refresh = bool(data.get("force_refresh", False))

        # Kiểm tra cache trong bộ nhớ để trả kết quả tức thì (0ms)
        if not force_refresh and state.cached_subjects and not manual_session:
            return {
                "status": "ok",
                "subjects": state.cached_subjects,
                "total_subjects": len(state.cached_subjects),
                "total_classes": len(state.cached_courses),
                "from_cache": True
            }

        if not state.session or manual_session:
            session, msg = resolve_session(manual_session)
            state.session = session
        else:
            session = state.session

        crawler = MoodleCrawler(session=session)
        raw_courses = crawler.get_enrolled_courses()

        course_list = []
        for c in raw_courses:
            clean_name = format_course_folder_name(c.name)
            folder_name = sanitize_filesystem_name(clean_name)

            code_match = re.match(r"^([A-Z0-9-]+)\s*-\s*(.*)$", clean_name)
            if code_match:
                code = code_match.group(1).strip()
                title = code_match.group(2).lstrip("- ").strip()
            else:
                code = c.id
                title = clean_name.lstrip("- ").strip()

            class_match = re.search(r"-(M\d+)-(\d{4}-\d{2})", c.name, flags=re.IGNORECASE)
            if class_match:
                class_code = class_match.group(1).upper()
                academic_year = class_match.group(2)
            else:
                m_match = re.search(r"-(M\d+)", c.name, flags=re.IGNORECASE)
                class_code = m_match.group(1).upper() if m_match else ""
                y_match = re.search(r"(\d{4}-\d{2})", c.name)
                academic_year = y_match.group(1) if y_match else ""

            course_list.append({
                "id": c.id,
                "name": clean_name,
                "code": code,
                "title": title,
                "subject_key": clean_name,
                "class_code": class_code,
                "academic_year": academic_year,
                "raw_name": c.name,
                "url": c.url,
                "folder_name": folder_name
            })

        subjects = group_courses_by_subject(course_list)
        # Lưu vào cache
        state.cached_subjects = subjects
        state.cached_courses = course_list

        return {
            "status": "ok",
            "subjects": subjects,
            "total_subjects": len(subjects),
            "total_classes": len(course_list),
            "from_cache": False
        }
    except Exception as e:
        return {"status": "error", "message": f"Lỗi nạp môn học từ Moodle: {str(e)}"}


# API: Lấy các đợt nộp bài (Turnitin drops) của 1 môn học kèm deadline đã phân tích
@app.route("/api/submissions/drops", method="POST")
def get_submission_drops():
    try:
        data = request.json or {}
        course_id = str(data.get("course_id", "")).strip()
        manual_session = data.get("session_id", "").strip()
        force_refresh = bool(data.get("force_refresh", False))

        if not course_id:
            return {"status": "error", "message": "Thiếu course_id"}

        # Trả về từ cache nếu có sẵn
        if not force_refresh and course_id in state.cached_drops and not manual_session:
            return {
                "status": "ok",
                "course_id": course_id,
                "drops": state.cached_drops[course_id],
                "total": len(state.cached_drops[course_id]),
                "from_cache": True
            }

        if not state.session or manual_session:
            session, _ = resolve_session(manual_session)
            state.session = session
        else:
            session = state.session

        crawler = TurnitinSubmissionCrawler(session=session)
        drops_raw = crawler.get_course_submission_drops(course_id)

        drops_list = []
        for d in drops_raw:
            detail = crawler.get_drop_details(d.cm_id)
            if detail:
                parts_data = []
                for p in detail.parts:
                    parts_data.append({
                        "part_id": p.part_id,
                        "part_name": p.part_name,
                        "start_date": p.start_date,
                        "due_date": p.due_date,
                        "post_date": p.post_date,
                        "max_marks": p.max_marks,
                        "due_date_iso": p.due_date_iso,
                        "days_left": p.days_left,
                        "deadline_status": p.deadline_status,
                        "deadline_badge": p.deadline_badge
                    })

                clean_drop_title = d.title.strip() if (d.title and len(d.title.strip()) > 3) else detail.title
                drops_list.append({
                    "cm_id": detail.cm_id,
                    "title": clean_drop_title,
                    "url": detail.url,
                    "section_name": d.section_name,
                    "assignment_id": detail.assignment_id,
                    "sesskey": detail.sesskey,
                    "primary_due_date": detail.primary_due_date,
                    "primary_due_iso": detail.primary_due_iso,
                    "days_left": detail.days_left,
                    "deadline_status": detail.deadline_status,
                    "deadline_badge": detail.deadline_badge,
                    "parts": parts_data,
                    "course_id": course_id
                })

        # Sắp xếp các đợt nộp: sắp xếp theo hạn nộp (đợt gần nhất/sắp tới hạn lên đầu)
        def sort_key(drop_item):
            iso = drop_item.get("primary_due_iso") or ""
            days = drop_item.get("days_left")
            if days is not None and days >= 0:
                # Đang mở hoặc sắp tới hạn: ưu tiên cao nhất
                return (0, days, iso)
            elif days is not None:
                # Đã kết thúc: xếp theo gần nhất
                return (1, -days, iso)
            return (2, 9999, iso)

        drops_list.sort(key=sort_key)
        state.cached_drops[course_id] = drops_list
        state.add_submission_log(f"Đã tìm thấy {len(drops_list)} đợt nộp bài Coursework cho môn học #{course_id}.", "info")

        return {
            "status": "ok",
            "course_id": course_id,
            "drops": drops_list,
            "total": len(drops_list),
            "from_cache": False
        }
    except Exception as e:
        return {"status": "error", "message": f"Lỗi quét đợt nộp bài: {str(e)}"}


# API: Quét song song đợt nộp cho nhiều lớp trong cùng một môn học (ThreadPoolExecutor)
@app.route("/api/submissions/subject-drops", method="POST")
def get_subject_all_drops():
    try:
        data = request.json or {}
        course_ids = data.get("course_ids", [])
        manual_session = data.get("session_id", "").strip()
        force_refresh = bool(data.get("force_refresh", False))

        if not course_ids:
            return {"status": "error", "message": "Thiếu danh sách course_ids"}

        if not state.session or manual_session:
            session, _ = resolve_session(manual_session)
            state.session = session
        else:
            session = state.session

        import concurrent.futures
        combined_drops = []
        seen_cm_ids = set()

        def fetch_single_course(cid):
            cid_str = str(cid)
            if not force_refresh and cid_str in state.cached_drops:
                return state.cached_drops[cid_str]
            crawler = TurnitinSubmissionCrawler(session=session)
            drops_raw = crawler.get_course_submission_drops(cid_str)
            drops_list = []
            for d in drops_raw:
                detail = crawler.get_drop_details(d.cm_id)
                if detail:
                    parts_data = []
                    for p in detail.parts:
                        parts_data.append({
                            "part_id": p.part_id,
                            "part_name": p.part_name,
                            "start_date": p.start_date,
                            "due_date": p.due_date,
                            "post_date": p.post_date,
                            "max_marks": p.max_marks,
                            "due_date_iso": p.due_date_iso,
                            "days_left": p.days_left,
                            "deadline_status": p.deadline_status,
                            "deadline_badge": p.deadline_badge
                        })
                    clean_drop_title = d.title.strip() if (d.title and len(d.title.strip()) > 3) else detail.title
                    drops_list.append({
                        "cm_id": detail.cm_id,
                        "title": clean_drop_title,
                        "url": detail.url,
                        "section_name": d.section_name,
                        "assignment_id": detail.assignment_id,
                        "sesskey": detail.sesskey,
                        "primary_due_date": detail.primary_due_date,
                        "primary_due_iso": detail.primary_due_iso,
                        "days_left": detail.days_left,
                        "deadline_status": detail.deadline_status,
                        "deadline_badge": detail.deadline_badge,
                        "parts": parts_data,
                        "course_id": cid_str
                    })
            state.cached_drops[cid_str] = drops_list
            return drops_list

        # Chạy song song tối đa 4 workers để tránh quá tải server Moodle
        max_workers = min(len(course_ids), 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = executor.map(fetch_single_course, course_ids)
            for res_list in results:
                for d in res_list:
                    if d["cm_id"] not in seen_cm_ids:
                        seen_cm_ids.add(d["cm_id"])
                        combined_drops.append(d)

        # Sắp xếp theo hạn nộp
        def sort_key(drop_item):
            iso = drop_item.get("primary_due_iso") or ""
            days = drop_item.get("days_left")
            if days is not None and days >= 0:
                return (0, days, iso)
            elif days is not None:
                return (1, -days, iso)
            return (2, 9999, iso)

        combined_drops.sort(key=sort_key)
        state.add_submission_log(f"Đã quét song song {len(course_ids)} lớp, tìm thấy tổng cộng {len(combined_drops)} đợt nộp.", "info")

        return {
            "status": "ok",
            "drops": combined_drops,
            "total": len(combined_drops)
        }
    except Exception as e:
        return {"status": "error", "message": f"Lỗi quét song song các lớp: {str(e)}"}


# API: Lấy danh sách sinh viên & bài nộp trong 1 Part
@app.route("/api/submissions/list", method="POST")
def get_part_submissions_list():
    try:
        data = request.json or {}
        drop_url = data.get("drop_url", "").strip()
        assignment_id = str(data.get("assignment_id", "")).strip()
        part_id = str(data.get("part_id", "")).strip()
        sesskey = data.get("sesskey", "").strip()
        manual_session = data.get("session_id", "").strip()

        if not assignment_id or not part_id:
            return {"status": "error", "message": "Thiếu assignment_id hoặc part_id"}

        if not state.session or manual_session:
            session, _ = resolve_session(manual_session)
            state.session = session
        else:
            session = state.session

        crawler = TurnitinSubmissionCrawler(session=session)
        items = crawler.get_part_submissions(
            drop_url=drop_url,
            assignment_id=assignment_id,
            part_id=part_id,
            sesskey=sesskey
        )

        submissions_data = []
        submitted_count = 0

        for it in items:
            if it.has_submission:
                submitted_count += 1
            submissions_data.append({
                "student_id": it.student_id,
                "student_name": it.student_name,
                "student_profile_url": it.student_profile_url,
                "paper_id": it.paper_id,
                "submission_title": it.submission_title,
                "submitted_at": it.submitted_at,
                "similarity_score": it.similarity_score,
                "similarity_text": it.similarity_text,
                "grade": it.grade,
                "max_grade": it.max_grade,
                "overall_grade": it.overall_grade,
                "has_submission": it.has_submission,
                "download_id": it.download_id
            })

        state.add_submission_log(f"Đã tải {len(submissions_data)} sinh viên ({submitted_count} đã nộp bài) cho Part #{part_id}.", "info")

        return {
            "status": "ok",
            "part_id": part_id,
            "submissions": submissions_data,
            "total": len(submissions_data),
            "submitted_count": submitted_count
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# API: Tải bài nộp của 1 sinh viên
@app.route("/api/submissions/download-single", method="POST")
def download_single_submission():
    try:
        data = request.json or {}
        drop_url = data.get("drop_url", "").strip()
        assignment_id = str(data.get("assignment_id", "")).strip()
        submission_id = str(data.get("submission_id", "")).strip()
        course_name = data.get("course_name", "Course")
        drop_title = data.get("drop_title", "Coursework")
        part_name = data.get("part_name", "Part")
        student_name = data.get("student_name", "")
        student_id = data.get("student_id", "")
        submission_title = data.get("submission_title", "")

        if not assignment_id or not submission_id:
            return {"status": "error", "message": "Thiếu assignment_id hoặc submission_id"}

        if not state.session:
            return {"status": "error", "message": "Chưa có phiên đăng nhập Moodle"}

        clean_course = sanitize_filesystem_name(format_course_folder_name(course_name))
        clean_drop = sanitize_filesystem_name(drop_title)
        clean_part = sanitize_filesystem_name(part_name)
        target_dir = Path(SUBMISSIONS_OUTPUT_DIR) / clean_course / clean_drop / clean_part

        prefix = f"{student_id}_{student_name}_{submission_title}" if student_id else f"{student_name}_{submission_title}"
        crawler = TurnitinSubmissionCrawler(session=state.session)

        saved_path = crawler.download_single_submission(
            drop_url=drop_url,
            assignment_id=assignment_id,
            submission_id=submission_id,
            save_folder=target_dir,
            suggested_prefix=prefix
        )

        if saved_path and saved_path.exists():
            import urllib.parse
            state.add_submission_log(f"Tải thành công bài nộp: {saved_path.name}", "success")
            return {
                "status": "ok",
                "file_name": saved_path.name,
                "file_path": str(saved_path),
                "download_url": f"/api/submissions/download-file?file_path={urllib.parse.quote(str(saved_path))}"
            }
        else:
            return {"status": "error", "message": "Không thể tải file bài nộp từ Turnitin"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# API: Bắt đầu tải loạt bài nộp (Background Worker)
@app.route("/api/submissions/download-batch", method="POST")
def download_batch_submissions():
    if state.is_downloading_submissions:
        return {"status": "error", "message": "Một tiến trình tải bài nộp khác đang chạy!"}

    if not state.session:
        return {"status": "error", "message": "Chưa xác thực phiên Moodle!"}

    data = request.json or {}
    course_name = data.get("course_name", "Course")
    drop_title = data.get("drop_title", "Coursework")
    drop_url = data.get("drop_url", "")
    assignment_id = str(data.get("assignment_id", ""))
    part_name = data.get("part_name", "Part 1")
    target_submissions = data.get("submissions", [])

    if not target_submissions:
        return {"status": "error", "message": "Danh sách bài nộp cần tải đang trống!"}

    t = threading.Thread(
        target=submission_download_worker,
        args=(state.session, course_name, drop_title, drop_url, assignment_id, part_name, target_submissions),
        daemon=True
    )
    t.start()

    return {"status": "ok", "message": f"Bắt đầu tải {len(target_submissions)} bài nộp!"}


# API: Tải file ZIP chính thức của toàn bộ đợt nộp từ Turnitin
@app.route("/api/submissions/download-zip", method="POST")
def download_part_zip():
    try:
        data = request.json or {}
        drop_url = data.get("drop_url", "")
        assignment_id = str(data.get("assignment_id", ""))
        part_id = str(data.get("part_id", ""))
        course_name = data.get("course_name", "Course")
        drop_title = data.get("drop_title", "Coursework")
        part_name = data.get("part_name", f"Part_{part_id}")

        if not assignment_id or not part_id:
            return {"status": "error", "message": "Thiếu assignment_id hoặc part_id"}

        if not state.session:
            return {"status": "error", "message": "Chưa xác thực phiên Moodle!"}

        clean_course = sanitize_filesystem_name(format_course_folder_name(course_name))
        clean_drop = sanitize_filesystem_name(drop_title)
        target_dir = Path(SUBMISSIONS_OUTPUT_DIR) / clean_course / clean_drop

        zip_name = f"{clean_drop}_{sanitize_filesystem_name(part_name)}_All_Submissions.zip"
        state.add_submission_log(f"Đang yêu cầu tạo và tải file ZIP từ Turnitin ({zip_name})...", "info")

        crawler = TurnitinSubmissionCrawler(session=state.session)
        saved_zip = crawler.download_part_zip(
            drop_url=drop_url,
            assignment_id=assignment_id,
            part_id=part_id,
            save_folder=target_dir,
            zip_filename=zip_name
        )

        if saved_zip and saved_zip.exists():
            import urllib.parse
            state.add_submission_log(f"Đã tải thành công file ZIP: {saved_zip.name}", "success")
            return {
                "status": "ok",
                "file_name": saved_zip.name,
                "file_path": str(saved_zip),
                "download_url": f"/api/submissions/download-file?file_path={urllib.parse.quote(str(saved_zip))}"
            }
        else:
            return {"status": "error", "message": "Turnitin không thể tạo file ZIP cho đợt nộp này"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# API: Tải file về trình duyệt trực tiếp (File stream / attachment)
@app.route("/api/submissions/download-file", method=["GET", "POST"])
def download_submission_file():
    file_path_str = request.query.get("file_path") or (request.json or {}).get("file_path", "")
    if not file_path_str:
        return {"status": "error", "message": "Thiếu file_path"}

    p = Path(file_path_str).resolve()
    if not p.exists() or not p.is_file():
        return {"status": "error", "message": "File không tồn tại trên hệ thống"}

    return static_file(p.name, root=str(p.parent), download=p.name)


# API: Tải file ZIP mới nhất đã đóng gói sau khi tải loạt
@app.route("/api/submissions/download-last-zip", method="GET")
def download_last_zip():
    if not state.submissions_last_zip_path:
        return {"status": "error", "message": "Chưa có file ZIP nào được tạo"}

    p = Path(state.submissions_last_zip_path).resolve()
    if not p.exists():
        return {"status": "error", "message": "File ZIP không tồn tại"}

    return static_file(p.name, root=str(p.parent), download=p.name)


# API: Hủy tiến trình tải submissions
@app.route("/api/submissions/download/cancel", method="POST")
def cancel_submissions_download():
    if state.is_downloading_submissions:
        state.should_stop_submissions = True
        state.add_submission_log("Đã yêu cầu dừng tải bài nộp...", "warning")
        return {"status": "ok", "message": "Đang dừng tải bài nộp..."}
    return {"status": "ok", "message": "Không có tiến trình tải bài nộp nào đang chạy."}


# API: Lấy trạng thái tải submissions (polling realtime)
@app.route("/api/submissions/status", method="GET")
def get_submissions_status():
    submissions_path = Path(SUBMISSIONS_OUTPUT_DIR)
    total_files_on_disk = 0
    total_size_bytes = 0
    if submissions_path.exists():
        for f in submissions_path.glob("**/*.*"):
            if f.is_file() and not f.name.endswith(".part"):
                total_files_on_disk += 1
                try:
                    total_size_bytes += f.stat().st_size
                except Exception:
                    pass

    return {
        "is_downloading": state.is_downloading_submissions,
        "current_course": state.submissions_current_course,
        "current_drop": state.submissions_current_drop,
        "current_student": state.submissions_current_student,
        "current_file": state.submissions_current_file,
        "total_downloaded": state.submissions_total_downloaded,
        "total_target": state.submissions_total_target,
        "total_files_on_disk": total_files_on_disk,
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
        "last_zip_name": state.submissions_last_zip_name,
        "has_last_zip": bool(state.submissions_last_zip_path and Path(state.submissions_last_zip_path).exists()),
        "logs": state.submissions_logs[-60:],
    }


# API: Mở thư mục submissions trong Windows Explorer
@app.route("/api/submissions/open-folder", method="POST")
def open_submissions_folder():
    data = request.json or {}
    subpath = data.get("subpath", "")
    target_path = Path(SUBMISSIONS_OUTPUT_DIR)
    if subpath:
        target_path = target_path / subpath

    target_path.mkdir(parents=True, exist_ok=True)

    try:
        if sys.platform == "win32":
            os.startfile(str(target_path.resolve()))
        elif sys.platform == "darwin":
            os.system(f'open "{target_path.resolve()}"')
        else:
            os.system(f'xdg-open "{target_path.resolve()}"')
        return {"status": "ok", "path": str(target_path.resolve())}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def start_server(host="127.0.0.1", port=5000):
    url = f"http://{host}:{port}"
    print(f"\n" + "=" * 65)
    print(f"🚀 GREENWICH MOODLE CRAWLER GUI ĐANG CHẠY TẠI:")
    print(f"👉 {url}")
    print("=" * 65 + "\n")

    # Tự động mở trình duyệt sau 1.2s
    def open_browser():
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    bottle.run(app, host=host, port=port, quiet=True)


if __name__ == "__main__":
    start_server()
