import re
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import requests
from lxml import html as lh

# Thiết lập encoding UTF-8 cho console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import MOODLE_BASE_URL, REQUEST_DELAY, DEFAULT_EXTENSIONS


@dataclass
class MoodleResourceItem:
    """Mô tả một item tài nguyên cần tải"""
    id: str
    title: str
    url: str             # URL view hoặc URL tải trực tiếp
    file_type: str       # 'resource', 'folder', 'assign', 'direct'
    extension: str = ""
    folder_name: str = ""


@dataclass
class CourseSection:
    """Mô tả một Section (Tuần / Chủ đề) trong khóa học"""
    id: str
    index: int
    name: str
    items: List[MoodleResourceItem] = field(default_factory=list)


@dataclass
class MoodleCourse:
    """Mô tả một khóa học Moodle"""
    id: str
    name: str
    url: str
    sections: List[CourseSection] = field(default_factory=list)


class MoodleCrawler:
    def __init__(self, session: requests.Session, allowed_extensions: Optional[List[str]] = None):
        self.session = session
        self.allowed_extensions = [ext.lower() for ext in (allowed_extensions or DEFAULT_EXTENSIONS)]

    def _safe_get(self, url: str, retries: int = 3, backoff: float = 2.0, **kwargs) -> Optional[requests.Response]:
        """Gửi GET request với cơ chế tự động thử lại nhiều lần nếu mạng bị chập chờn."""
        for attempt in range(1, retries + 1):
            try:
                time.sleep(REQUEST_DELAY)
                res = self.session.get(url, timeout=30, **kwargs)
                return res
            except Exception as e:
                if attempt == retries:
                    print(f"    [!] Lỗi kết nối sau {retries} lần thử ({url[:60]}...): {e}", flush=True)
                    return None
                print(f"    [!] Mạng chập chờn ({e}). Đang thử lại lần {attempt + 1}/{retries} sau {backoff * attempt}s...", flush=True)
                time.sleep(backoff * attempt)
        return None

    def get_enrolled_courses(self) -> List[MoodleCourse]:
        """
        Lấy danh sách tất cả các khóa học mà sinh viên đang theo học từ trang chủ Moodle.
        """
        print("[*] Đang tải danh sách các khóa học từ Moodle Home...", flush=True)
        res = self._safe_get(MOODLE_BASE_URL)
        if not res:
            raise ConnectionError(f"Không thể kết nối tới Moodle Home: {MOODLE_BASE_URL}")

        tree = lh.fromstring(res.content)
        course_links = tree.xpath('//a[contains(@href, "course/view.php?id=")]')

        courses: List[MoodleCourse] = []
        seen_ids = set()

        for a in course_links:
            href = a.attrib.get("href", "")
            match = re.search(r"id=(\d+)", href)
            if not match:
                continue

            course_id = match.group(1)
            if course_id == "1" or course_id in seen_ids:
                continue

            raw_text = a.text_content().strip()
            clean_name = " ".join(raw_text.split())

            if not clean_name:
                continue

            seen_ids.add(course_id)
            course_url = f"{MOODLE_BASE_URL}/course/view.php?id={course_id}"
            courses.append(MoodleCourse(id=course_id, name=clean_name, url=course_url))

        print(f"[+] Tìm thấy tổng cộng {len(courses)} khóa học.", flush=True)
        return courses

    def get_course_sections(self, course: MoodleCourse) -> List[CourseSection]:
        """
        Quét nhanh cấu trúc HTML của khóa học để lấy danh sách các section và các liên kết tài liệu.
        Chỉ tốn 1 request duy nhất tới trang khóa học, cực kỳ nhanh!
        """
        print(f"\n[*] Đang quét cấu trúc môn học: {course.name} ...", flush=True)
        res = self._safe_get(course.url)
        if not res:
            print(f"[!] Không thể tải trang môn học {course.name}, bỏ qua môn này.", flush=True)
            return []

        tree = lh.fromstring(res.content)
        section_nodes = tree.xpath('//li[starts-with(@id, "section-")]')
        if not section_nodes:
            section_nodes = tree.xpath('//*[contains(@class, "section") and starts-with(@id, "section-")]')

        sections: List[CourseSection] = []

        for idx, s_node in enumerate(section_nodes):
            s_id = s_node.attrib.get("id", f"section-{idx}")
            
            # Lấy tên tiêu đề section
            name_nodes = s_node.xpath(
                './/*[contains(@class, "sectionname")]//text() | '
                './/h3[contains(@class, "section-title")]//text() | '
                './/*[contains(@class, "section-title")]//text()'
            )
            raw_title = " ".join("".join(name_nodes).split())
            if not raw_title:
                raw_title = f"Section_{idx}"

            section = CourseSection(id=s_id, index=idx, name=raw_title)

            # Thu thập các link tài nguyên trong section
            items = self._collect_section_raw_items(s_node)
            section.items = items
            sections.append(section)

        course.sections = sections
        total_items = sum(len(s.items) for s in sections)
        print(f"[+] Khóa học có {len(sections)} sections với tổng cộng {total_items} mục tài nguyên tiềm năng.", flush=True)
        return sections

    def _collect_section_raw_items(self, section_node) -> List[MoodleResourceItem]:
        """
        Thu thập các liên kết tài liệu thô trong section mà không cần gửi thêm request HTTP.
        """
        items: List[MoodleResourceItem] = []
        seen_urls = set()

        # 1. mod/resource
        res_links = section_node.xpath('.//a[contains(@href, "/mod/resource/view.php?id=")]')
        for link in res_links:
            href = link.attrib.get("href", "")
            if href in seen_urls:
                continue
            seen_urls.add(href)
            match = re.search(r"id=(\d+)", href)
            res_id = match.group(1) if match else "res"

            title_node = link.xpath('.//*[contains(@class, "instancename")]/text()')
            title = title_node[0].strip() if title_node else " ".join(link.text_content().split())
            title = re.sub(r"\s*(File|Document)\s*$", "", title, flags=re.IGNORECASE).strip()

            items.append(MoodleResourceItem(
                id=res_id,
                title=title,
                url=href,
                file_type="resource",
            ))

        # 2. mod/folder
        folder_links = section_node.xpath('.//a[contains(@href, "/mod/folder/view.php?id=")]')
        for link in folder_links:
            href = link.attrib.get("href", "")
            if href in seen_urls:
                continue
            seen_urls.add(href)
            match = re.search(r"id=(\d+)", href)
            folder_id = match.group(1) if match else "folder"

            title_node = link.xpath('.//*[contains(@class, "instancename")]/text()')
            title = title_node[0].strip() if title_node else " ".join(link.text_content().split())
            title = re.sub(r"\s*(Folder)\s*$", "", title, flags=re.IGNORECASE).strip()

            items.append(MoodleResourceItem(
                id=folder_id,
                title=title,
                url=href,
                file_type="folder",
                folder_name=title
            ))

        # 3. Direct pluginfile.php
        direct_links = section_node.xpath('.//a[contains(@href, "pluginfile.php")]')
        for link in direct_links:
            href = link.attrib.get("href", "")
            if href in seen_urls:
                continue
            seen_urls.add(href)
            ext = self._get_extension_from_url(href)
            if self._is_allowed_extension(href, ext):
                title = " ".join(link.text_content().split()) or "file"
                items.append(MoodleResourceItem(
                    id="direct",
                    title=title,
                    url=href,
                    file_type="direct",
                    extension=ext
                ))

        # 4. mod/assign
        assign_links = section_node.xpath('.//a[contains(@href, "/mod/assign/view.php?id=")]')
        for link in assign_links:
            href = link.attrib.get("href", "")
            if href in seen_urls:
                continue
            seen_urls.add(href)
            match = re.search(r"id=(\d+)", href)
            assign_id = match.group(1) if match else "assign"

            title_node = link.xpath('.//*[contains(@class, "instancename")]/text()')
            title = title_node[0].strip() if title_node else " ".join(link.text_content().split())
            title = re.sub(r"\s*(Assignment)\s*$", "", title, flags=re.IGNORECASE).strip()

            items.append(MoodleResourceItem(
                id=assign_id,
                title=title,
                url=href,
                file_type="assign",
            ))

        return items

    def resolve_resource_file(self, item: MoodleResourceItem) -> List[Tuple[str, str, str]]:
        """
        Phân giải một MoodleResourceItem thành danh sách các file tải về thực tế:
        Trả về: [(download_url, suggested_title, folder_name), ...]
        """
        results = []

        if item.file_type == "direct":
            results.append((item.url, item.title, item.folder_name))
            return results

        elif item.file_type == "resource":
            try:
                r = self._safe_get(item.url, allow_redirects=True)
                if not r:
                    return results

                if "pluginfile.php" in r.url:
                    results.append((r.url, item.title, item.folder_name))
                    return results

                tree = lh.fromstring(r.content)
                links = tree.xpath(
                    '//div[contains(@class, "resourceworkaround")]//a/@href | '
                    '//div[contains(@class, "resourcecontent")]//a/@href | '
                    '//a[contains(@href, "pluginfile.php")]/@href'
                )
                for l in links:
                    if "pluginfile.php" in l:
                        results.append((l, item.title, item.folder_name))
                        return results

                embeds = tree.xpath('//object/@data | //iframe/@src | //embed/@src')
                for e in embeds:
                    if "pluginfile.php" in e:
                        results.append((e, item.title, item.folder_name))
                        return results

            except Exception as e:
                print(f"    [!] Lỗi khi phân giải resource ({item.title}): {e}", flush=True)

        elif item.file_type == "folder":
            try:
                r = self._safe_get(item.url)
                if not r:
                    return results

                tree = lh.fromstring(r.content)
                file_links = tree.xpath('//a[contains(@href, "pluginfile.php")]')
                for a in file_links:
                    href = a.attrib.get("href", "")
                    text = " ".join(a.text_content().split())
                    ext = self._get_extension_from_url(href)
                    if self._is_allowed_extension(href, ext):
                        file_title = text or href.split("?")[0].split("/")[-1]
                        results.append((href, file_title, item.folder_name))
            except Exception as e:
                print(f"    [!] Lỗi khi phân giải folder ({item.title}): {e}", flush=True)

        elif item.file_type == "assign":
            try:
                r = self._safe_get(item.url)
                if not r:
                    return results

                tree = lh.fromstring(r.content)
                files = tree.xpath('//div[contains(@id, "intro")]//a[contains(@href, "pluginfile.php")]')
                for a in files:
                    href = a.attrib.get("href", "")
                    text = " ".join(a.text_content().split())
                    ext = self._get_extension_from_url(href)
                    if self._is_allowed_extension(href, ext):
                        brief_title = text or f"{item.title}_Brief"
                        results.append((href, brief_title, item.folder_name))
            except Exception:
                pass

        return results

    def _get_extension_from_url(self, url: str) -> str:
        clean_url = url.split("?")[0].split("#")[0]
        filename = clean_url.split("/")[-1]
        dot_idx = filename.rfind(".")
        if dot_idx != -1:
            ext = filename[dot_idx:].lower()
            if len(ext) <= 6 and "/" not in ext:
                return ext
        return ""

    def _is_allowed_extension(self, url: str, ext: str) -> bool:
        if ext and ext.lower() in self.allowed_extensions:
            return True
        clean_url = url.split("?")[0].lower()
        for allowed in self.allowed_extensions:
            if clean_url.endswith(allowed):
                return True
        return False
