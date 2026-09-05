# Hướng Dẫn Trích Xuất & Cấu Hình Moodle Session (Cho Mọi Trình Duyệt) 🔑

Tài liệu này hướng dẫn chi tiết cách lấy cookie phiên đăng nhập (`MoodleSession`) từ bất kỳ trình duyệt nào (**Google Chrome, Microsoft Edge, Brave, Cốc Cốc, Safari, Firefox**) trên máy tính khác và dán vào file `.env` để chạy crawler mà không cần cài đặt Firefox.

---

## 🎯 Khi Nào Cần Dùng Cách Này?
- Bạn chạy tool trên máy tính khác không có Firefox.
- Bạn dùng Chrome/Edge làm trình duyệt chính đã đăng nhập Greenwich Moodle.
- Bạn chạy tool trên VPS / Docker / Linux server không có giao diện đồ họa.

---

## 📌 Cách 1: Lấy qua Công Cụ Nhà Phát Triển (DevTools F12) - Rất Đơn Giản

Áp dụng cho **Google Chrome**, **Microsoft Edge**, **Brave**, **Cốc Cốc**:

1. Mở trình duyệt và truy cập vào trang:  
   👉 **`https://moodlecurrent.gre.ac.uk/`**
2. Đảm bảo bạn đã đăng nhập thành công và thấy giao diện trang chủ Moodle (danh sách môn học).
3. Nhấn phím **`F12`** (hoặc click chuột phải vào bất kỳ đâu trên trang chọn **Inspect** / **Kiểm tra**).
4. Trên thanh tab của cửa sổ DevTools vừa mở:
   - Chọn tab **Application** (hoặc **Ứng dụng**).
   - *Nếu dùng Firefox*: Chọn tab **Storage** (hoặc **Bộ nhớ**).
5. Ở cột bên trái, tìm mục **Cookies**:
   - Nhấn mở rộng và click chọn `https://moodlecurrent.gre.ac.uk`.
6. Ở bảng bên phải, tìm dòng có cột **Name** là:
   ```
   MoodleSession
   ```
7. Double-click vào giá trị trong cột **Value**, click chuột phải chọn **Copy** (Giá trị thường là một chuỗi ký tự ngẫu nhiên dài khoảng 26 - 32 ký tự, ví dụ: `k4d8n9s2b7a1v5c3x8z0q1w4e7`).
8. Mở thư mục dự án `module_crawler`:
   - Tạo file tên là `.env` (hoặc nhân bản từ file `.env.example`).
   - Dán giá trị vừa copy vào dòng `MOODLE_SESSION=`:
     ```env
     MOODLE_SESSION=k4d8n9s2b7a1v5c3x8z0q1w4e7
     ```
   - Lưu file `.env` lại.

---

## 📌 Cách 2: Lấy qua Tiện Ích Mở Rộng (Extension Cookie Editor) - Cực Nhanh

Nếu bạn hay dùng hoặc muốn tiện lợi trong 1 cú click:
1. Cài extension **Cookie-Editor** (có sẵn trên Chrome Web Store và Firefox Add-ons).
2. Mở trang `https://moodlecurrent.gre.ac.uk/`.
3. Click vào icon **Cookie-Editor** trên thanh công cụ của trình duyệt.
4. Tìm cookie có tên `MoodleSession`.
5. Copy giá trị trong ô **Value** và dán vào file `.env`:
   ```env
   MOODLE_SESSION=chuỗi_value_vừa_copy
   ```

---

## 📌 Cách 3: Lấy từ Tab Network (Bất Kỳ Trình Duyệt Nào)

1. Nhấn **`F12`** -> chọn tab **Network** (Mạng).
2. Tải lại trang (F5).
3. Click vào dòng đầu tiên (thường là `moodlecurrent.gre.ac.uk` hoặc `view.php`).
4. Ở bảng bên phải, chọn tab **Headers** -> cuộn xuống mục **Request Headers**.
5. Tìm dòng `Cookie:`.
6. Bạn sẽ thấy đoạn `MoodleSession=abcxyz123;`. Chỉ cần copy đoạn giá trị sau dấu `=` và trước dấu `;`.

---

## 🧪 Kiểm Tra Hoạt Động

Sau khi lưu file `.env`, bạn chỉ cần chạy:
```powershell
python main.py --list
```
Nếu màn hình thông báo:
```
[*] Đang sử dụng MOODLE_SESSION được cấu hình thủ công từ .env...
[+] Xác thực thủ công qua MOODLE_SESSION thành công!
```
Nghĩa là cấu hình đã thành công 100%! Bạn có thể bắt đầu tải tài liệu ngay.
