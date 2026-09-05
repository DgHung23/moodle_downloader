import os
from pathlib import Path
from dotenv import load_dotenv

# Tải biến môi trường từ file .env nếu có
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = Path(os.getenv("OUTPUTS_DIR", BASE_DIR / "outputs"))

# Moodle Greenwich URLs
MOODLE_BASE_URL = os.getenv("MOODLE_BASE_URL", "https://moodlecurrent.gre.ac.uk")

# Danh sách các định dạng tài liệu được tải mặc định
DEFAULT_EXTENSIONS = [
    ".pdf",
    ".pptx",
    ".ppt",
    ".zip",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".rar",
    ".7z",
]

# Cấu hình mạng
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.5"))  # Giây giữa các request để tránh spam server
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
)

# Cookie thủ công nếu không dùng Firefox profile (tùy chọn)
MANUAL_MOODLE_SESSION = os.getenv("MOODLE_SESSION", "").strip()
