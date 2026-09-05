# 🎓 Greenwich Moodle Document Crawler & GUI Downloader 📚

Ứng dụng tự động hóa thông minh giúp sinh viên Đại học Greenwich tải toàn bộ tài liệu học tập (`.pdf`, `.pptx`, `.zip`, `.docx`, `.xlsx`,...) từ cổng **Greenwich Moodle** (`https://moodlecurrent.gre.ac.uk/`). Hệ thống tự động bóc tách tài liệu và phân loại vào từng thư mục tương ứng theo quy chuẩn **`Mã Môn - Tên Môn`** và **`Tuần / Chủ đề (Section)`**.

---

## 🌟 Tính Năng Nổi Bật

### 1. 🖥️ Giao Diện Đồ Họa Trực Quan (Web GUI)
- **Thiết kế Dark Glassmorphism cao cấp**: Hiện đại, mượt mà, tối ưu trải nghiệm người dùng.
- **Thống kê thời gian thực**: Hiển thị tổng số khóa học, số tài liệu đã lưu trên ổ cứng, dung lượng tải về.
- **Thanh tiến trình & Nhật ký động**: Theo dõi từng file đang được tải về cùng tốc độ và dung lượng.
- **Nút mở thư mục tức thì**: Bấm 1 click để mở trực tiếp thư mục khóa học trong Windows Explorer.

### 2. ⚡ Tự Động Trích Xuất Phiên Đăng Nhập (Auto-detect Session)
- **🦊 Mozilla Firefox**: Tự động đọc an toàn cookie và token SSO từ Firefox (hoạt động tốt kể cả khi Firefox đang mở).
- **🌊 Microsoft Edge**: Tự động giải mã cookie Chromium qua Windows DPAPI & AES-GCM.
- **🌐 Google Chrome**: Tự động phát hiện và giải mã cookie từ các profile của Chrome.
- **🔑 Nhập thủ công**: Hỗ trợ nhập trực tiếp `MoodleSession` qua ô nhập liệu trên Web GUI hoặc cấu hình trong file `.env`.

### 3. 📁 Phân Cấp Thư Mục Chuẩn Hóa
- Tự động chuẩn hóa và loại bỏ các ký tự cấm trên Windows (`< > : " / \ | ? *`).
- Cấu trúc thư mục được sắp xếp khoa học:
  ```
  outputs/
  ├── COMP-1845 - Systems Development/
  │   ├── 02_Get Started/
  │   │   └── COMP 1845-System Development TNE Module Handbook- 2024-2025.pdf
  │   ├── 07_Introduction Lecture-Week1/
  │   │   ├── Emerging Digital Technology and database system.pptx
  │   │   └── Tutorial Practical a.docx
  │   ├── 08_Database contents Terms and contents definitions-Week2/
  │   │   └── Database contents Terms and contents definitions.pptx
  │   ...
  ├── MATH-1179 - Mathematics for Computer Science/
  │   ├── 07_Lecture Notes_workbook/
  │   │   ├── MATH1179 Workbook 2425.pdf
  │   │   └── maths-for-computer-sci-ff-for-web.pdf
  │   ├── 08_Sets/
  │   │   ├── Lecture 1 Sets.pptx
  │   │   └── Tutorial sets questions (and solutions).pdf
  │   ...
  └── COMP-1807 - Agile Development with SCRUM/
      ...
  ```

### 4. 🔍 Bóc Tách Đa Cấp Toàn Diện (Multi-level Crawling)
- Bóc tách file từ tài nguyên lẻ: `mod/resource`.
- Bóc tách toàn bộ file trong các thư mục con: `mod/folder`.
- Bóc tách tài liệu đề bài, rubric đính kèm trong bài tập: `mod/assign`.
- Bắt trực tiếp các đường dẫn tải file `pluginfile.php`.

### 5. 🛡️ Cơ Chế Chịu Lỗi Mạng & Bỏ Qua File Đã Tải (Resume & Skip Existing)
- **Tự động thử lại (Auto-Retry)**: Nếu mạng bị chập chờn hoặc timeout, chương trình tự động thử lại nhiều lần với cơ chế dãn cách thời gian.
- **Bảo vệ độc lập**: Nếu một môn học gặp sự cố, hệ thống sẽ tự động ghi log và tiếp tục tải các môn học tiếp theo mà không bị crash.
- **Skip Existing**: Kiểm tra kích thước file trước khi tải. Nếu file đã tồn tại trọn vẹn, chương trình sẽ bỏ qua trong mili-giây, tiết kiệm băng thông và thời gian khi chạy lại.

---

## 🛠️ Cài Đặt & Môi Trường

Yêu cầu máy tính đã cài đặt **Python 3.10+**.

Mở Terminal tại thư mục dự án và cài đặt các thư viện cần thiết:

```powershell
pip install -r requirements.txt
```

*(Các thư viện chính bao gồm: `requests`, `lxml`, `bottle`, `tqdm`, `cryptography`, `pywin32`, `python-dotenv`).*

---

## 🚀 Hướng Dẫn Sử Dụng

### ⚡ Cách 0: Chạy 1-Click Bằng File `run.bat` (Nhanh nhất & Tự Động Hoàn Toàn)

Chỉ cần **nhấp đúp chuột vào file `run.bat`**:
- Tự động kiểm tra Python trên máy.
- Tự động tạo file `.env` nếu chưa có.
- Tự động phát hiện và cài đặt toàn bộ thư viện thiếu trong `requirements.txt`.
- Tự động khởi chạy **Web GUI** sau 3 giây (hoặc bấm phím `2` nếu muốn dùng CLI).

---

### 🌟 Cách 1: Sử Dụng Giao Diện Web GUI (Khuyên dùng)

Chỉ cần chạy lệnh:
```powershell
python app.py
```
Hệ thống sẽ khởi động máy chủ cục bộ và tự động mở trình duyệt tại:  
👉 **`http://127.0.0.1:5000`**

**Quy trình sử dụng trên GUI:**
1. **Lấy Session**: Bấm một trong 3 nút:
   - **`🦊 Firefox`**: Tự động lấy từ Firefox.
   - **`🌊 Edge`**: Tự động lấy từ Microsoft Edge.
   - **`🌐 Chrome`**: Tự động lấy từ Google Chrome.
   - *(Hoặc dán `MoodleSession` thủ công vào ô nhập liệu nếu dùng máy khác)*.
2. **Fetch môn học**: Nhấn nút **"Fetch Các Môn Học"** để tải toàn bộ danh sách môn học.
3. **Tải tài liệu**:
   - Bấm **"Tải Môn Này"** trên thẻ môn học tương ứng.
   - Hoặc bấm **"⬇️ Tải Toàn Bộ Môn Học (Download All)"** ở góc trên để tải hết tất cả các môn.
4. **Mở thư mục**: Bấm **"Mở Thư Mục"** trên thẻ môn hoặc **"Mở Thư Mục Outputs"** trên thanh tiêu đề để xem tài liệu trong Windows Explorer.

---

### 💻 Cách 2: Sử Dụng Dòng Lệnh Tương Tác (CLI Menu)

Nếu thích làm việc qua terminal:
```powershell
python main.py
```
Chương trình sẽ liệt kê danh sách các môn kèm số thứ tự (ví dụ: `01` đến `19`). Bạn chỉ cần nhập số môn muốn tải (ví dụ: `1` hoặc `1,2,5` hoặc `0` để tải toàn bộ).

---

### 💻 Cách 3: Các Lệnh Dòng Lệnh Nâng Cao

```powershell
# Tải toàn bộ tất cả các môn học tự động
python main.py --all

# Chỉ tải một hoặc nhiều môn học cụ thể theo ID
python main.py --course-id 113052,112900

# Chỉ lọc các định dạng file nhất định
python main.py --extensions pdf,pptx,zip

# Chỉ xem danh sách môn học hiện có
python main.py --list
```

---

## 🔑 Hướng Dẫn Lấy MoodleSession Bằng Phím F12

Khi chuyển sang máy tính khác hoặc dùng trình duyệt chưa đăng nhập tự động:

1. Truy cập **`https://moodlecurrent.gre.ac.uk/`** và đăng nhập.
2. Nhấn phím **`F12`** để mở DevTools.
3. Chọn tab **Application** (với Chrome/Edge) hoặc tab **Storage** (với Firefox).
4. Ở cột bên trái, chọn **Cookies** &rarr; **`https://moodlecurrent.gre.ac.uk`**.
5. Tìm dòng có Name là **`MoodleSession`**, copy chuỗi Value và:
   - Dán trực tiếp vào ô Session trên Web GUI, HOẶC
   - Tạo file `.env` và dán vào: `MOODLE_SESSION=giá_trị_vừa_copy`

> 📖 Xem hướng dẫn chi tiết kèm hình ảnh tại: [HUONG_DAN_LAY_SESSION.md](file:///e:/Greenwich/AI_Lab/module_crawler/HUONG_DAN_LAY_SESSION.md) hoặc truy cập trang hướng dẫn trên GUI tại `http://127.0.0.1:5000/static/guide.html`.

---

## 📂 Cấu Trúc Mã Nguồn Dự Án

```
module_crawler/
├── app.py                     # Máy chủ Web GUI (Bottle API & Background Task Worker)
├── auth.py                    # Module xác thực tự động (Firefox, Edge, Chrome SSO)
├── crawler.py                 # Engine quét Moodle, phân tích Sections & tài liệu
├── downloader.py              # Engine tải file dạng stream, skip existing, chuẩn hóa tên
├── main.py                    # Giao diện dòng lệnh CLI tương tác
├── config.py                  # Các thông số cấu hình mặc định
├── requirements.txt           # Danh sách thư viện Python phụ thuộc
├── .env.example               # Mẫu file cấu hình môi trường
├── README.md                  # Hướng dẫn sử dụng tổng quan
├── HUONG_DAN_LAY_SESSION.md   # Hướng dẫn chi tiết trích xuất MoodleSession qua F12
└── web/
    ├── index.html             # Giao diện Web GUI chính
    ├── guide.html             # Trang hướng dẫn lấy cookie F12 trực quan
    ├── style.css              # Hệ thống CSS Dark Glassmorphism
    └── app.js                 # Logic điều khiển giao diện & cập nhật realtime
```
