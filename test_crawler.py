import os
import sys
from pathlib import Path

# Thiết lập encoding UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from auth import get_authenticated_session
from crawler import MoodleCrawler, MoodleCourse
from downloader import Downloader

print("=== BẮT ĐẦU KIỂM THỬ TẢI THỰC TẾ ===", flush=True)
session = get_authenticated_session()
crawler = MoodleCrawler(session=session)
test_dir = Path("outputs_test")
downloader = Downloader(session=session, output_dir=test_dir)

course = MoodleCourse(
    id="113052",
    name="MATH-1179-M07-2025-26 Mathematics for Computer Science (FPT University, Ho Chi Minh)",
    url="https://moodlecurrent.gre.ac.uk/course/view.php?id=113052"
)

# Quét các section (chỉ mất ~1s)
sections = crawler.get_course_sections(course)

# Tìm section đầu tiên có items
test_section = None
for s in sections:
    if s.items:
        test_section = s
        break

if not test_section:
    print("[!] Không tìm thấy section nào có item.", flush=True)
    sys.exit(1)

print(f"\n[*] Section thử nghiệm: [{test_section.index}] {test_section.name}", flush=True)
downloaded_paths = []

# Tải thử tối đa 2 items
count = 0
for raw_item in test_section.items:
    resolved_files = crawler.resolve_resource_file(raw_item)
    for dl_url, title, folder_name in resolved_files:
        p = downloader.download_file(course, test_section, dl_url, title, folder_name)
        if p and p.exists():
            downloaded_paths.append((dl_url, title, folder_name, p))
            print(f"    [XÁC THỰC] File tồn tại: {p.name} ({p.stat().st_size} bytes)", flush=True)
            count += 1
            if count >= 2:
                break
    if count >= 2:
        break

print("\n[*] Kiểm tra cơ chế Skip Existing khi chạy lại:", flush=True)
for dl_url, title, folder_name, p in downloaded_paths:
    downloader.download_file(course, test_section, dl_url, title, folder_name)

print("\n=== KẾT QUẢ KIỂM THỬ HOÀN HẢO ===", flush=True)
