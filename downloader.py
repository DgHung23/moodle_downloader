import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Optional
import requests
from tqdm import tqdm

# Thiết lập encoding UTF-8 cho console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import OUTPUTS_DIR, REQUEST_TIMEOUT
from crawler import MoodleCourse, CourseSection


def sanitize_filesystem_name(name: str, max_length: int = 150) -> str:
    """
    Chuẩn hóa tên thư mục hoặc tên file cho an toàn trên hệ điều hành Windows:
    - Loại bỏ các ký tự cấm: < > : " / \\ | ? *
    - Bỏ khoảng trắng và dấu chấm ở đầu/cuối
    - Giới hạn độ dài để tránh vượt quá giới hạn 260 ký tự đường dẫn của Windows
    """
    if not name:
        return "unnamed"
    
    clean = re.sub(r'[<>:"/\\|?*]', "_", name)
    clean = " ".join(clean.split()).strip(". ")
    
    if len(clean) > max_length:
        clean = clean[:max_length].rstrip(". ")
        
    return clean or "unnamed"


def format_course_folder_name(raw_name: str) -> str:
    """
    Định dạng tên thư mục môn học theo cú pháp:
    [Mã Môn] - [Tên Môn] (Ví dụ: COMP-1845 - Systems Development)
    Loại bỏ các thông tin thừa như mã kỳ (-M06-2025-26) và cơ sở (FPT University, Ho Chi Minh).
    """
    # 1. Bỏ phần trường/cơ sở ở cuối nếu có: (FPT...)
    name = re.sub(r'\s*\(\s*FPT[^)]*\)\s*$', '', raw_name, flags=re.IGNORECASE).strip()
    
    # 2. Bắt dạng CODE-NUM (kèm theo mã kỳ/năm như -M07-2025-26 hoặc -2024-25) rồi đến Tên Môn
    m = re.match(r'^([A-Z]+-\d+|[A-Z]\d+)(?:-[A-Za-z0-9]+)*(?:-\d{4}-\d{2})?\s+(.*)$', name)
    if m:
        code = m.group(1).strip()
        title = m.group(2).strip().lstrip("- ").strip()
        if title:
            return f"{code} - {title}"
        return code
    return name


def format_section_folder_name(raw_name: str, index: int = 0) -> str:
    """
    Chuẩn hóa tên thư mục section để gộp thống nhất giữa các lớp khác nhau của cùng môn học:
    - Loại bỏ ký tự cấm trên Windows
    - Chuẩn hóa số tuần / số topic thành 2 chữ số (Week 1 -> Week 01, Topic 2 -> Topic 02) để Windows Explorer sắp xếp đúng thứ tự
    - Đảm bảo các lớp khác nhau có cùng tiêu đề tuần sẽ gom chung vào 1 thư mục duy nhất
    """
    if not raw_name:
        return f"{index:02d}_Section" if index > 0 else "Section"

    clean = sanitize_filesystem_name(raw_name)

    # Chuẩn hóa Week X -> Week 0X, Topic X -> Topic 0X, Chapter X -> Chapter 0X
    clean = re.sub(r'\bWeek\s*(\d)\b', r'Week 0\1', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bTopic\s*(\d)\b', r'Topic 0\1', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\bChapter\s*(\d)\b', r'Chapter 0\1', clean, flags=re.IGNORECASE)

    # Nếu tên section đã có định danh rõ ràng như Week, Topic, Chapter hoặc số thứ tự thì giữ nguyên
    if re.match(r'^(?:Week|Topic|Chapter|\d+)', clean, flags=re.IGNORECASE):
        return clean

    # Với các section chung (Get Started, Coursework Submission...) gắn prefix 2 chữ số để xếp đúng thứ tự
    if index > 0:
        prefix = f"{index:02d}_"
        if not clean.startswith(prefix):
            clean = f"{prefix}{clean}"

    return clean


class Downloader:
    def __init__(self, session: requests.Session, output_dir: Optional[Path] = None):
        self.session = session
        self.output_dir = Path(output_dir or OUTPUTS_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download_file(
        self,
        course: MoodleCourse,
        section: CourseSection,
        download_url: str,
        suggested_title: str,
        folder_name: str = "",
        course_folder_name: str = "",
    ) -> Optional[Path]:
        """
        Tải một file tài liệu cụ thể và lưu vào cấu trúc thư mục tương ứng:
        outputs/[Mã Môn - Tên môn học]/[Section Index - Tên section]/[Tên folder con]/[Tên file]
        Ví dụ: outputs/COMP-1857 - Introduction to Data Science/Week 01 - Introduction to Data Science/Slide.pdf
        """
        # Định dạng tên thư mục môn học theo chuẩn: COMP... - Tên Môn
        if course_folder_name:
            course_dir_name = sanitize_filesystem_name(course_folder_name)
        else:
            course_display_name = format_course_folder_name(course.name)
            course_dir_name = sanitize_filesystem_name(course_display_name)

        # Chuẩn hóa tên thư mục section thống nhất giữa các lớp
        section_dir_name = format_section_folder_name(section.name, section.index)

        dest_dir = self.output_dir / course_dir_name / section_dir_name

        if folder_name:
            subfolder_clean = sanitize_filesystem_name(folder_name)
            dest_dir = dest_dir / subfolder_clean

        dest_dir.mkdir(parents=True, exist_ok=True)

        try:
            res = self.session.get(download_url, stream=True, timeout=REQUEST_TIMEOUT)
            res.raise_for_status()

            filename = self._determine_filename(res, suggested_title, download_url)
            filename = sanitize_filesystem_name(filename)
            final_path = dest_dir / filename
            part_path = dest_dir / f"{filename}.part"

            content_length = int(res.headers.get("Content-Length", 0))

            # Skip existing files nếu đã có
            if final_path.exists():
                file_size = final_path.stat().st_size
                if content_length > 0 and file_size == content_length:
                    print(f"    [=] Đã có: {filename} ({file_size / (1024*1024):.2f} MB)", flush=True)
                    return final_path
                elif content_length == 0 and file_size > 0:
                    print(f"    [=] Đã có: {filename}", flush=True)
                    return final_path

            # Ghi file theo chunk
            chunk_size = 1024 * 64
            with open(part_path, "wb") as f, tqdm(
                total=content_length,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=f"    [v] {filename[:30]}",
                leave=False,
            ) as pbar:
                for chunk in res.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))

            if part_path.exists():
                if final_path.exists():
                    final_path.unlink()
                part_path.rename(final_path)

            file_size_mb = final_path.stat().st_size / (1024 * 1024)
            print(f"    [+] Tải thành công: {filename} ({file_size_mb:.2f} MB)", flush=True)
            return final_path

        except Exception as e:
            print(f"    [!] Lỗi khi tải file ({suggested_title}): {e}", flush=True)
            if 'part_path' in locals() and part_path.exists():
                try:
                    part_path.unlink()
                except Exception:
                    pass
            return None

    def _determine_filename(self, response: requests.Response, suggested_title: str, url: str) -> str:
        # 1. Content-Disposition
        cd = response.headers.get("Content-Disposition", "")
        if cd:
            match_utf8 = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.IGNORECASE)
            if match_utf8:
                return urllib.parse.unquote(match_utf8.group(1))

            match_std = re.search(r'filename="?([^";\n]+)"?', cd)
            if match_std:
                return match_std.group(1).strip()

        # 2. URL basename
        clean_url = response.url.split("?")[0].split("#")[0]
        url_filename = clean_url.split("/")[-1]
        if url_filename and "." in url_filename:
            return urllib.parse.unquote(url_filename)

        # 3. Suggested title + extension from url or content-type
        title = suggested_title
        if not re.search(r'\.[a-zA-Z0-9]{2,5}$', title):
            # Cố gắng tìm extension từ clean_url gốc
            orig_url_clean = url.split("?")[0]
            if "." in orig_url_clean:
                ext = orig_url_clean[orig_url_clean.rfind("."):]
                if len(ext) <= 6:
                    title += ext

        return title or "downloaded_file"
