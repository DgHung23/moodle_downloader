import base64
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import requests
from lxml import html as lh

# Thiết lập encoding UTF-8 cho console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import MOODLE_BASE_URL, USER_AGENT, MANUAL_MOODLE_SESSION


# ==============================================================================
# 1. TRÍCH XUẤT TỪ FIREFOX
# ==============================================================================
def get_firefox_profile_path() -> Optional[Path]:
    """Tìm thư mục profile Firefox của người dùng trên Windows."""
    app_data = os.getenv("APPDATA")
    if not app_data:
        return None

    profiles_dir = Path(app_data) / "Mozilla" / "Firefox" / "Profiles"
    if not profiles_dir.exists():
        return None

    candidate_profiles = []
    for p in profiles_dir.iterdir():
        if p.is_dir() and (p / "cookies.sqlite").exists():
            candidate_profiles.append(p)

    if not candidate_profiles:
        return None

    for p in candidate_profiles:
        if "default-release" in p.name.lower():
            return p

    candidate_profiles.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidate_profiles[0]


def extract_cookies_from_firefox(profile_path: Optional[Path] = None) -> List[Dict]:
    """Trích xuất cookies từ Firefox (hoạt động tốt kể cả khi Firefox đang mở)."""
    if profile_path is None:
        profile_path = get_firefox_profile_path()
    if not profile_path:
        return []

    src_db = profile_path / "cookies.sqlite"
    if not src_db.exists():
        return []

    temp_dir = Path(tempfile.gettempdir()) / f"ff_cookies_{int(time.time() * 1000)}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    tmp_db = temp_dir / "cookies.sqlite"

    try:
        shutil.copy2(src_db, tmp_db)
        src_wal = profile_path / "cookies.sqlite-wal"
        if src_wal.exists():
            shutil.copy2(src_wal, temp_dir / "cookies.sqlite-wal")

        conn = sqlite3.connect(tmp_db)
        cur = conn.cursor()
        query = """
            SELECT host, name, value, path, isSecure
            FROM moz_cookies
            WHERE host LIKE '%gre.ac.uk%' 
               OR host LIKE '%microsoft%' 
               OR host LIKE '%moodle%'
        """
        cur.execute(query)
        rows = cur.fetchall()
        conn.close()

        cookie_list = []
        for host, name, value, path, is_secure in rows:
            cookie_list.append({
                "host": host,
                "name": name,
                "value": value,
                "path": path,
                "is_secure": bool(is_secure),
                "browser": "firefox"
            })
        return cookie_list

    except Exception as e:
        print(f"[!] Lỗi khi trích xuất cookie từ Firefox: {e}", flush=True)
        return []
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# 2. TRÍCH XUẤT TỪ GOOGLE CHROME & MICROSOFT EDGE (CHROMIUM)
# ==============================================================================
def extract_cookies_from_chromium(browser_name: str = "edge") -> Tuple[List[Dict], str]:
    """
    Trích xuất và giải mã cookies từ Google Chrome hoặc Microsoft Edge trên Windows.
    Sử dụng DPAPI và AES-GCM để giải mã trường encrypted_value trong SQLite.
    Trả về: (cookie_list, status_message)
    """
    local_app = os.getenv("LOCALAPPDATA")
    if not local_app:
        return [], "Không tìm thấy thư mục LOCALAPPDATA trên hệ thống."

    if browser_name.lower() == "chrome":
        display_name = "Google Chrome"
        base_dir = Path(local_app) / "Google" / "Chrome" / "User Data"
    elif browser_name.lower() == "edge":
        display_name = "Microsoft Edge"
        base_dir = Path(local_app) / "Microsoft" / "Edge" / "User Data"
    else:
        return [], f"Trình duyệt '{browser_name}' không được hỗ trợ."

    if not base_dir.exists():
        return [], f"Không tìm thấy thư mục cài đặt của {display_name} trên máy tính này."

    local_state_path = base_dir / "Local State"
    if not local_state_path.exists():
        return [], f"Không tìm thấy file Local State của {display_name}."

    # Kiểm tra thư viện giải mã
    try:
        import win32crypt
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return [], "Thiếu thư viện pywin32 hoặc cryptography để giải mã cookie Chromium."

    # Giải mã master key từ Local State qua Windows DPAPI
    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            local_state = json.load(f)
        encrypted_key_b64 = local_state.get("os_crypt", {}).get("encrypted_key", "")
        if not encrypted_key_b64:
            return [], f"Không tìm thấy encrypted_key trong Local State của {display_name}."

        encrypted_key = base64.b64decode(encrypted_key_b64)
        if not encrypted_key.startswith(b"DPAPI"):
            return [], f"Khóa mã hóa của {display_name} không dùng định dạng DPAPI thông thường."

        master_key = win32crypt.CryptUnprotectData(encrypted_key[5:], None, None, None, 0)[1]
    except Exception as e:
        return [], f"Lỗi khi giải mã master key của {display_name}: {e}"

    # Quét các profile: Default, Profile 1, Profile 2...
    profiles = ["Default"] + [f"Profile {i}" for i in range(1, 10)]
    all_cookies = []
    locked_error = False

    for prof in profiles:
        prof_dir = base_dir / prof
        if not prof_dir.exists():
            continue

        possible_paths = [
            prof_dir / "Network" / "Cookies",
            prof_dir / "Cookies",
        ]
        cookie_file = next((p for p in possible_paths if p.exists()), None)
        if not cookie_file:
            continue

        temp_db = Path(tempfile.gettempdir()) / f"{browser_name}_{prof}_cookies_{int(time.time()*1000)}.sqlite"
        try:
            shutil.copy2(cookie_file, temp_db)
        except PermissionError:
            locked_error = True
            continue
        except Exception as e:
            if "used by another process" in str(e).lower():
                locked_error = True
            continue

        try:
            conn = sqlite3.connect(temp_db)
            cur = conn.cursor()
            cur.execute(
                "SELECT host_key, name, encrypted_value, path "
                "FROM cookies "
                "WHERE host_key LIKE '%gre.ac.uk%' OR host_key LIKE '%moodle%' OR host_key LIKE '%microsoft%'"
            )
            rows = cur.fetchall()

            for host, name, enc_val, path in rows:
                val = ""
                if enc_val.startswith(b"v10") or enc_val.startswith(b"v11"):
                    nonce = enc_val[3:15]
                    ciphertext = enc_val[15:]
                    aesgcm = AESGCM(master_key)
                    try:
                        val = aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
                    except Exception:
                        continue
                elif enc_val:
                    try:
                        val = win32crypt.CryptUnprotectData(enc_val, None, None, None, 0)[1].decode("utf-8")
                    except Exception:
                        continue

                if val:
                    all_cookies.append({
                        "host": host,
                        "name": name,
                        "value": val,
                        "path": path,
                        "browser": browser_name.lower()
                    })
            conn.close()
        except Exception as e:
            print(f"[!] Lỗi khi đọc bảng cookies {display_name} ({prof}): {e}", flush=True)
        finally:
            if temp_db.exists():
                try: temp_db.unlink()
                except Exception: pass

    if all_cookies:
        return all_cookies, f"Đã trích xuất thành công {len(all_cookies)} cookies từ {display_name}!"

    if locked_error:
        return [], f"{display_name} đang mở và khóa file dữ liệu cookies. Vui lòng đóng {display_name} rồi bấm lại nút này, hoặc nhấn F12 theo hướng dẫn trong HUONG_DAN_LAY_SESSION.md."

    return [], f"Không tìm thấy cookies Moodle nào trong {display_name}. Bạn đã đăng nhập Moodle trên trình duyệt này chưa?"


# ==============================================================================
# 3. TRÌNH QUẢN LÝ PHIÊN MẠNG (AUTHENTICATED SESSION)
# ==============================================================================
def get_authenticated_session(manual_session_id: Optional[str] = None) -> requests.Session:
    """Tạo requests.Session đã được xác thực hoàn chỉnh với Moodle Greenwich."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
    })

    # 1. Thử dùng session thủ công
    token = manual_session_id or MANUAL_MOODLE_SESSION
    if token and token.strip():
        token = token.strip()
        print("[*] Đang kiểm tra MoodleSession được cung cấp...", flush=True)
        session.cookies.set("MoodleSession", token, domain="moodlecurrent.gre.ac.uk", path="/")
        res = session.get(MOODLE_BASE_URL, timeout=15)
        if "My modules" in res.text or "course/view.php" in res.text:
            print("[+] Xác thực thủ công qua MoodleSession thành công!", flush=True)
            return session
        print("[!] MoodleSession cung cấp không hợp lệ hoặc đã hết hạn. Đang tự động tìm từ trình duyệt...", flush=True)

    # 2. Thử tự động từ Firefox
    profile_path = get_firefox_profile_path()
    if profile_path:
        print(f"[*] Tìm thấy Firefox profile: {profile_path.name}", flush=True)
        cookies = extract_cookies_from_firefox(profile_path)
        print(f"[*] Đã trích xuất {len(cookies)} cookies từ Firefox.", flush=True)

        for c in cookies:
            domain = c["host"].lstrip(".")
            session.cookies.set(name=c["name"], value=c["value"], domain=domain, path=c["path"])

        print("[*] Đang kết nối tới Moodle Greenwich để kiểm tra xác thực...", flush=True)
        res = session.get(MOODLE_BASE_URL, allow_redirects=True, timeout=20)

        # Xử lý tự động chuyển tiếp Microsoft SSO OIDC callback nếu có form ẩn
        if "hiddenform" in res.text and "auth/oidc" in res.text:
            print("[*] Phát hiện phản hồi Microsoft SSO. Đang tự động hoàn tất xác thực OIDC...", flush=True)
            tree = lh.fromstring(res.content)
            form = tree.xpath('//form[@name="hiddenform"]')[0]
            action = form.attrib.get("action")
            data = {inp.attrib.get("name"): inp.attrib.get("value", "") for inp in form.xpath(".//input") if inp.attrib.get("name")}
            res = session.post(action, data=data, allow_redirects=True, timeout=20)

        if "My modules" in res.text or "course/view.php" in res.text:
            print("[+] Đăng nhập Moodle thành công thông qua Firefox SSO session!", flush=True)
            return session

    # 3. Thử tự động từ Edge
    edge_cookies, _ = extract_cookies_from_chromium("edge")
    if edge_cookies:
        for c in edge_cookies:
            domain = c["host"].lstrip(".")
            session.cookies.set(name=c["name"], value=c["value"], domain=domain, path=c["path"])
        res = session.get(MOODLE_BASE_URL, allow_redirects=True, timeout=20)
        if "My modules" in res.text or "course/view.php" in res.text:
            print("[+] Đăng nhập Moodle thành công thông qua Edge session!", flush=True)
            return session

    raise RuntimeError(
        "Không thể tự động xác thực vào Moodle Greenwich!\n"
        "Vui lòng đảm bảo bạn đã đăng nhập vào https://moodlecurrent.gre.ac.uk/,\n"
        "hoặc cung cấp MoodleSession theo hướng dẫn trong file HUONG_DAN_LAY_SESSION.md."
    )
