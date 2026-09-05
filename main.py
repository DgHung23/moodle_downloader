import argparse
import sys
import time
from pathlib import Path
from typing import List

# Thiết lập encoding UTF-8 cho console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from auth import get_authenticated_session
from config import OUTPUTS_DIR, DEFAULT_EXTENSIONS
from crawler import MoodleCrawler, MoodleCourse
from downloader import Downloader, format_course_folder_name


def print_banner():
    banner = """
========================================================================
     GREENWICH MOODLE DOCUMENT CRAWLER (PDF, PPTX, ZIP, DOCX...)
========================================================================
    """
    print(banner, flush=True)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Crawler tự động tải tài liệu học tập từ Greenwich Moodle phân loại theo môn học và tuần."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Tự động tải toàn bộ tài liệu của tất cả các môn học hiện có.",
    )
    parser.add_argument(
        "--course-id",
        type=str,
        help="ID môn học cần tải (ví dụ: 113052 hoặc nhiều ID cách nhau bằng dấu phẩy: 113052,112900).",
    )
    parser.add_argument(
        "--extensions",
        type=str,
        help=f"Danh sách định dạng file cần tải cách nhau bằng dấu phẩy (Mặc định: {','.join([e.lstrip('.') for e in DEFAULT_EXTENSIONS])}).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(OUTPUTS_DIR),
        help="Đường dẫn thư mục lưu trữ tài liệu đầu ra.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Chỉ liệt kê danh sách môn học mà không thực hiện tải về.",
    )
    parser.add_argument(
        "--unique",
        "--dedup",
        action="store_true",
        help="Chế độ lọc môn học trùng lặp (chỉ giữ lại các môn duy nhất, tự động gộp các lớp).",
    )
    return parser.parse_args()


def select_courses_interactively(courses: List[MoodleCourse], default_dedup: bool = True) -> List[MoodleCourse]:
    """
    Hiển thị danh sách khóa học và cho phép người dùng chọn số thứ tự.
    Hỗ trợ bấm phím 'u' để chuyển đổi qua lại giữa chế độ Lọc Trùng Lặp và Hiện Tất Cả.
    """
    dedup_mode = default_dedup

    while True:
        if dedup_mode:
            groups = {}
            for c in courses:
                key = format_course_folder_name(c.name)
                if key not in groups:
                    groups[key] = []
                groups[key].append(c)

            group_keys = list(groups.keys())
            print("\n" + "=" * 70, flush=True)
            print(f" DANH SÁCH MÔN HỌC (ĐÃ LỌC TRÙNG: {len(group_keys)} MÔN DUY NHẤT TỪ {len(courses)} LỚP):", flush=True)
            print("=" * 70, flush=True)
            for idx, key in enumerate(group_keys, 1):
                class_list = groups[key]
                class_count = len(class_list)
                count_str = f"({class_count} lớp học - tự gộp đủ file)" if class_count > 1 else f"(ID: {class_list[0].id})"
                print(f"  [{idx:02d}] {key} {count_str}", flush=True)
            print("-" * 70, flush=True)
            print("  [00] TẢI TOÀN BỘ TẤT CẢ CÁC MÔN HỌC Ở TRÊN", flush=True)
            print("  [u]  BẬT/TẮT LỌC TRÙNG LẶP (Hiện tại: ĐANG BẬT -> Nhập 'u' để xem tất cả lớp)", flush=True)
            print("=" * 70, flush=True)
        else:
            print("\n" + "=" * 70, flush=True)
            print(f" DANH SÁCH TOÀN BỘ CÁC LỚP HỌC TRÊN MOODLE ({len(courses)} LỚP):", flush=True)
            print("=" * 70, flush=True)
            for idx, c in enumerate(courses, 1):
                clean_title = format_course_folder_name(c.name)
                print(f"  [{idx:02d}] {clean_title} (ID: {c.id})", flush=True)
            print("-" * 70, flush=True)
            print("  [00] TẢI TOÀN BỘ TẤT CẢ CÁC MÔN HỌC Ở TRÊN", flush=True)
            print("  [u]  BẬT/TẮT LỌC TRÙNG LẶP (Hiện tại: ĐANG TẮT -> Nhập 'u' để gộp môn duy nhất)", flush=True)
            print("=" * 70, flush=True)

        try:
            choice = input("\n👉 Nhập số thứ tự môn muốn tải (ví dụ: 1 hoặc 1,3 hoặc 0 để chọn hết, u để đổi chế độ, q để thoát): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nĐã hủy thao tác.", flush=True)
            sys.exit(0)

        if choice.lower() in ["q", "quit", "exit"]:
            print("Đã thoát chương trình.", flush=True)
            sys.exit(0)

        if choice.lower() == "u":
            dedup_mode = not dedup_mode
            continue

        if choice in ["0", "00", "all"]:
            if dedup_mode:
                # Trả về danh sách đã được nhóm theo từng môn để tải trọn vẹn từng môn
                grouped_courses = []
                for key in group_keys:
                    grouped_courses.extend(groups[key])
                return grouped_courses
            return courses

        tokens = [t.strip() for t in choice.replace(";", ",").replace(" ", ",").split(",") if t.strip()]
        valid = True
        max_idx = len(group_keys) if dedup_mode else len(courses)
        selected_courses = []

        for t in tokens:
            if not t.isdigit():
                print(f"[!] '{t}' không phải là số hợp lệ.", flush=True)
                valid = False
                break
            num = int(t)
            if num < 1 or num > max_idx:
                print(f"[!] Số {num} nằm ngoài phạm vi danh sách (1 - {max_idx}).", flush=True)
                valid = False
                break

            if dedup_mode:
                key = group_keys[num - 1]
                # Thêm tất cả các lớp của môn học này để gộp tài liệu đầy đủ
                selected_courses.extend(groups[key])
            else:
                selected_courses.append(courses[num - 1])

        if valid and selected_courses:
            unique_selected = []
            seen = set()
            for c in selected_courses:
                if c.id not in seen:
                    seen.add(c.id)
                    unique_selected.append(c)
            return unique_selected


def run_crawl():
    print_banner()
    args = parse_arguments()

    # 1. Xác thực phiên làm việc
    session = get_authenticated_session()

    # 2. Xử lý phần mở rộng file
    if args.extensions:
        allowed_exts = [f".{ext.strip().lstrip('.')}" for ext in args.extensions.split(",") if ext.strip()]
    else:
        allowed_exts = DEFAULT_EXTENSIONS

    print(f"[*] Định dạng file cho phép: {', '.join(allowed_exts)}", flush=True)
    print(f"[*] Thư mục lưu trữ: {Path(args.output_dir).resolve()}", flush=True)

    crawler = MoodleCrawler(session=session, allowed_extensions=allowed_exts)
    downloader = Downloader(session=session, output_dir=Path(args.output_dir))

    # 3. Lấy danh sách khóa học
    all_courses = crawler.get_enrolled_courses()
    if not all_courses:
        print("[!] Không tìm thấy khóa học nào trong tài khoản của bạn.", flush=True)
        return

    if args.list:
        if args.unique:
            groups = {}
            for c in all_courses:
                key = format_course_folder_name(c.name)
                if key not in groups:
                    groups[key] = []
                groups[key].append(c)
            print(f"\nDanh sách môn học duy nhất ({len(groups)} môn từ {len(all_courses)} lớp):", flush=True)
            for idx, (key, class_list) in enumerate(groups.items(), 1):
                print(f"  {idx:02d}. {key} ({len(class_list)} lớp học)", flush=True)
        else:
            print(f"\nDanh sách toàn bộ khóa học ({len(all_courses)} lớp):", flush=True)
            for idx, c in enumerate(all_courses, 1):
                clean_title = format_course_folder_name(c.name)
                print(f"  {idx:02d}. [ID: {c.id}] {clean_title}", flush=True)
        return

    # 4. Xác định các khóa học sẽ crawl
    target_courses: List[MoodleCourse] = []
    if args.course_id:
        target_ids = [cid.strip() for cid in args.course_id.split(",") if cid.strip()]
        for c in all_courses:
            if c.id in target_ids:
                target_courses.append(c)
        if not target_courses:
            print(f"[!] Không tìm thấy khóa học nào khớp với ID: {args.course_id}", flush=True)
            return
    elif args.all:
        if args.unique or (len(all_courses) > 20):
            groups = {}
            for c in all_courses:
                key = format_course_folder_name(c.name)
                if key not in groups:
                    groups[key] = []
                groups[key].append(c)
            target_courses = []
            for k in groups:
                target_courses.extend(groups[k])
        else:
            target_courses = all_courses
    else:
        target_courses = select_courses_interactively(all_courses, default_dedup=(len(all_courses) > 20 or args.unique))

    # Gom nhóm các lớp theo môn học để xử lý trọn vẹn từng môn
    subject_groups = {}
    for c in target_courses:
        subj_name = format_course_folder_name(c.name)
        if subj_name not in subject_groups:
            subject_groups[subj_name] = []
        subject_groups[subj_name].append(c)

    print(f"\n🚀 Bắt đầu quá trình tải tài liệu cho {len(subject_groups)} môn học (tổng hợp từ {len(target_courses)} lớp đã chọn)...\n", flush=True)

    total_downloaded = 0
    total_failed = 0
    start_time = time.time()

    for s_idx, (subject_title, class_list) in enumerate(subject_groups.items(), 1):
        class_desc = f"{len(class_list)} lớp"
        print("\n" + "#" * 70, flush=True)
        print(f"[{s_idx}/{len(subject_groups)}] ĐANG XỬ LÝ MÔN: {subject_title} (Gộp {class_desc})", flush=True)
        print("#" * 70, flush=True)

        subj_downloaded = 0
        for course in class_list:
            try:
                sections = crawler.get_course_sections(course)

                for s in sections:
                    if not s.items:
                        continue

                    section_printed = False
                    for raw_item in s.items:
                        # Phân giải link thực tế on-demand
                        resolved_files = crawler.resolve_resource_file(raw_item)
                        for download_url, suggested_title, folder_name in resolved_files:
                            if not section_printed:
                                print(f"\n  📁 Section: {s.name}", flush=True)
                                section_printed = True

                            out_path = downloader.download_file(
                                course=course,
                                section=s,
                                download_url=download_url,
                                suggested_title=suggested_title,
                                folder_name=folder_name,
                                course_folder_name=subject_title,
                            )
                            if out_path:
                                total_downloaded += 1
                                subj_downloaded += 1
                            else:
                                total_failed += 1
            except Exception as e:
                print(f"[!] Gặp lỗi khi xử lý lớp {course.name}: {e}. Đang tiếp tục...", flush=True)

        print(f"[*] Đã hoàn tất môn [{s_idx}/{len(subject_groups)}]: {subject_title} (Đã xử lý {subj_downloaded} files)", flush=True)

    elapsed = time.time() - start_time
    print("\n" + "=" * 70, flush=True)
    print("🎉 HOÀN TẤT QUÁ TRÌNH CRAWL TÀI LIỆU!", flush=True)
    print(f"⏱  Thời gian thực thi : {elapsed:.1f} giây", flush=True)
    print(f"📊 Tổng file đã xử lý  : {total_downloaded + total_failed}", flush=True)
    print(f"📂 Thư mục lưu trữ      : {Path(args.output_dir).resolve()}", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    run_crawl()
