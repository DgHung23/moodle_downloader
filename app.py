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
from config import OUTPUTS_DIR, MOODLE_BASE_URL, DEFAULT_EXTENSIONS
from crawler import MoodleCrawler, MoodleCourse
from downloader import Downloader, format_course_folder_name, sanitize_filesystem_name

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

state = AppState()


# Helper: Tạo session từ cookie do người dùng cung cấp hoặc tự trích xuất
def resolve_session(user_session_id: Optional[str] = None):
    session = requests_session = None
    if user_session_id and user_session_id.strip():
        import requests
        session = requests.Session()
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
