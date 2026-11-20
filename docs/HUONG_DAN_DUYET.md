# Hướng dẫn duyệt dữ liệu OCR (phần {PART})

## 1. Việc bạn cần làm

Dữ liệu là các văn bản của Trường Đại học Thăng Long (quy chế, kế hoạch, thông báo...) đã được đọc bằng OCR. Một mô hình
LLM đã rà lại và **đề xuất sửa** một số chỗ. Việc của bạn: với từng chỗ đề xuất, xem **ảnh gốc** rồi quyết định
LLM sửa **Đúng** hay **Sai**. Kết quả của bạn được lưu vào một thư mục riêng, bạn nén lại và gửi cho người giao việc.

Phần của bạn là **phần {PART}**. Mỗi file chỉ thuộc về một người, nên bạn không cần lo trùng việc với người khác.

Máy của bạn **không cần** khóa API, GPU hay Internet (sau khi cài xong thư viện).

> Lưu ý bảo mật: bộ tài liệu có thể chứa họ tên, mã sinh viên, số điện thoại. **Không** đăng lên mạng, nhóm công khai,
> GitHub hay chia sẻ cho người ngoài nhóm.

## 2. Cài đặt (làm một lần)

### Windows

1. **Cài Python 3.10 trở lên** từ https://www.python.org/downloads/ . Khi cài, **tick vào "Add python.exe to PATH"**.
   Kiểm tra: mở PowerShell, gõ `python --version`, phải hiện `Python 3.x.x`.
2. **Giải nén** file zip vào một thư mục, ví dụ `C:\sar_review`. Nên đặt ở nơi đường dẫn **không dấu, không quá dài**.
3. **Mở PowerShell tại thư mục đó**: trong File Explorer, vào thư mục vừa giải nén, bấm vào thanh địa chỉ, gõ `powershell`
   rồi Enter.
4. Chạy lần lượt 3 lệnh:

   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements-review.txt
   ```

   Nếu lệnh `activate` báo lỗi về "execution policy", chạy `Set-ExecutionPolicy -Scope Process Bypass` rồi chạy lại.
   Sau lệnh `activate`, đầu dòng lệnh phải có chữ `(.venv)`.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-review.txt
```

## 3. Mở giao diện

Mỗi lần làm việc, mở PowerShell tại thư mục đã giải nén, kích hoạt môi trường rồi chạy:

```powershell
.venv\Scripts\activate
python review.py --part {PART}
```

- Khoảng 10-20 giây sau, trình duyệt tự mở trang `http://127.0.0.1:8765/index.html`. Trang này **chỉ máy bạn truy cập được**.
- **Không đóng cửa sổ PowerShell** trong lúc làm việc. Muốn dừng: bấm `Ctrl+C` trong cửa sổ đó.
- Nếu trình duyệt không tự mở: dán địa chỉ trên vào trình duyệt. Nếu cổng 8765 bận, chương trình tự đổi cổng và in địa chỉ mới.
- Sau khi cập nhật chương trình hoặc mở lại, nhấn `Ctrl+F5` để trình duyệt tải bản mới.
- Ảnh được tạo dần. Lần đầu mở một dòng có thể chờ 1-2 giây.

## 4. Cách duyệt

Mỗi chỗ cần duyệt là một dòng, có 2 hàng:

| Cột | Ý nghĩa |
|---|---|
| **Văn bản gốc (ảnh)** | Ảnh trang gốc, **khung đỏ là chỗ bị sửa**. Bấm vào ảnh để xem cả trang. Nếu không xác định được vị trí, ảnh là cả trang và có ghi chú. |
| **LLM sửa** | Hai ô cạnh nhau: **"OCR đọc"** (chữ OCR hiện có) và **"LLM sửa thành"**. Chữ khác nhau được tô màu: đỏ gạch ngang = bị bỏ, xanh = thêm vào. |
| **Đúng / Sai** | Mặc định là **Đúng** (chấp nhận LLM sửa). Chọn **Sai** nếu LLM sửa chưa đúng. Có thêm ô tick **Đã duyệt**. |
| **Sửa sai** | Chỉ dùng khi chọn Sai: gõ **chữ đúng** để thay cho đoạn "OCR đọc". |

Hàng thứ hai của mỗi dòng là **ô ngữ cảnh**: chữ xung quanh chỗ sửa trong văn bản OCR của trang. Chỗ bị sửa được tô **đỏ**
(OCR hiện tại) và **xanh** (sau khi LLM sửa), kèm số dòng của trang. Dùng ô này khi một trang có nhiều lỗi để biết chắc đang
xem đúng chỗ nào. Nếu đoạn xuất hiện nhiều lần trong trang, ô liệt kê tối đa 3 vị trí; chọn vị trí đúng theo ảnh.

### Quyết định cho mỗi dòng

1. **LLM sửa đúng** (khớp ảnh gốc): để nguyên **Đúng**, rồi tick **Đã duyệt**.
2. **LLM sửa sai, bạn biết chữ đúng**: chọn **Sai**, gõ chữ đúng vào ô **Sửa sai**.
3. **LLM sửa sai nhưng chữ OCR ban đầu vốn đúng**: chọn **Sai**, bấm **"Giữ nguyên chữ OCR đọc"**.
4. **Đoạn đó phải xóa bỏ (thành rỗng)**: chọn **Sai**, bấm **"Bỏ (xóa đoạn này)"** (hoặc để trống ô Sửa sai).
5. **Không chắc chữ đó đọc là gì**: **đừng đoán**. Bỏ trống (không tick Đã duyệt) và ghi lại để hỏi người giao việc.

Gõ chữ đúng thay cho **đúng đoạn "OCR đọc"**, không phải cả câu. Chỉ gõ chữ nhìn thấy trong ảnh, không thêm bớt.

### Về "Đã duyệt" và Accept

- Ô **Đã duyệt** tự tick khi bạn đổi Đúng/Sai hoặc gõ vào ô sửa. Dòng bạn xem rồi và thấy LLM đúng thì **tick tay**.
- Nút **"Đánh dấu đã duyệt các dòng đang hiện"** tick hàng loạt cho các dòng đang hiện (sau khi lọc). Chỉ dùng khi bạn **đã thật sự xem**.
- Nút **Accept** ghi **chỉ các dòng đã duyệt** vào kết quả. Các dòng đó biến mất khỏi danh sách; dòng chưa duyệt vẫn ở lại.
  Bạn có thể Accept nhiều lần, **nên Accept thường xuyên** (ví dụ sau mỗi 50-100 dòng).
- Các nút lọc: **"Chỉ hiện có cảnh báo"**, **"Chỉ hiện dòng Sai"**, **"Ẩn dòng đã duyệt"**.
- Dòng có **cảnh báo** (số liệu chưa được OCR thứ hai xác nhận, LLM chưa chắc, sửa cấu trúc bảng) được xếp **lên đầu**.
  Hãy xem kỹ các dòng này, nhất là **số liệu** (số tiền, ngày, điểm, mã học phần).

Tiến độ (đã duyệt, chọn Đúng/Sai) tự lưu. Tắt rồi mở lại vẫn còn.

## 5. Nộp kết quả

Sau mỗi đợt làm (hoặc khi xong):

1. **Accept** những dòng đã duyệt.
2. Bấm `Ctrl+C` trong cửa sổ PowerShell để dừng (không bắt buộc, nhưng nên làm trước khi nén).
3. **Nén thư mục `data\interim\corrected`** thành file zip (chuột phải > Nén / Send to > Compressed folder).
4. Đặt tên: `corrected_phan{PART_FILE}_ngay-thang.zip`, ví dụ `corrected_phan1_2_20-11.zip`.
5. Gửi file cho người giao việc (Drive/Zalo/email). File chỉ khoảng 8 MB.

Chỉ gửi **thư mục `corrected`**. Không sửa tay các file bên trong. Bạn có thể nộp nhiều lần; lần sau chứa cả kết quả lần trước.

## 6. Gặp lỗi

| Hiện tượng | Cách xử lý |
|---|---|
| `python` không được nhận ra | Cài lại Python và tick "Add python.exe to PATH", mở PowerShell mới. |
| `pip` báo không tải được thư viện | Kiểm tra mạng; chạy lại lệnh `pip install -r requirements-review.txt`. |
| Trang không mở / "refused" | Cửa sổ PowerShell đã đóng hoặc đã dừng. Chạy lại lệnh ở mục 3. |
| Giao diện vẫn như bản cũ | Nhấn `Ctrl+F5`. Nếu vẫn vậy, tắt hẳn cửa sổ lệnh cũ (`Ctrl+C`), chạy lại. |
| Ảnh không hiện | Đợi vài giây (ảnh tạo theo yêu cầu) rồi nhấn `Ctrl+F5`. |
| Accept báo lỗi | Đọc nội dung lỗi; thường là một dòng chọn Sai nhưng cần sửa. Chụp màn hình gửi người giao việc nếu không rõ. |
| Lỗi khác | Chụp màn hình cửa sổ PowerShell (và trang web) gửi người giao việc. |

## 7. Những điều cần tránh

- Đừng sửa file bên trong các thư mục `data\interim\extract` hoặc `data\raw`.
- Đừng chạy hai cửa sổ giao diện cho cùng một phần cùng lúc.
- Đừng Accept khi chưa xem. Dòng chưa xem hãy để nguyên.
- Đừng đoán chữ khi ảnh mờ hoặc không rõ.

## 8. Duyệt bảng do VLM đọc lại (ctdt) — `table-vlm-review-ui`

Dành cho người soát các trang bảng ctdt mà VLM đã đọc lại (`data/interim/table_vlm/`). Cùng cách chạy với giao diện ở mục 3: máy chủ cục bộ
chỉ nghe ở `127.0.0.1`, không cần Internet hay khóa API, tiến độ tự lưu.

```powershell
.venv\Scripts\activate
python scripts/ingest.py --stage table-vlm-review-ui
```

Trình duyệt tự mở `http://127.0.0.1:8765/index.html` (cổng bận thì tự đổi và in địa chỉ mới; thêm `--port`, `--no-browser` nếu cần).
Lần đầu **nhập tên vào ô "Người soát"** (được lưu cùng mỗi quyết định). Ảnh trang được dựng khi mở trang lần đầu (1-2 giây).

**Thanh bên** chọn hàng đợi, có tiến độ đã duyệt/tổng:

| Hàng đợi | Gồm |
|---|---|
| Ưu tiên | 11 trang trong `data/processed/table_vlm_samples/can_soat/` |
| ocr_recall thấp | trang đang dùng có `ocr_recall` < 0,7 |
| Spot check | các trang trong `data/processed/table_vlm_spot_check.md` |
| Còn need_review | trang bị loại (cân nhắc `force_accept`) |

Tick "chỉ hiện trang chưa duyệt" để ẩn trang đã có kết quả. Một trang có thể nằm trong nhiều hàng đợi; kết quả mới nhất của trang áp dụng cho mọi hàng.

**Mỗi trang:** bên trái là ảnh gốc (cuộn chuột để zoom tại con trỏ, kéo chuột để di chuyển, nút *Vừa khung*/*100%*). Bên phải:

- Ô thông tin: tỉ lệ số trùng, `ocr_recall`, `need_review`, `spot_check`, `continued_header`, `rows_fixed`.
- Tab **a) Bản VLM** (bảng Markdown vẽ thành bảng; số/mã chỉ có ở VLM tô **vàng**), **b) VLM thô** (kèm các chỗ khác bản chuẩn hóa),
  **c) OCR cũ** (số/mã có ở OCR nhưng không có ở VLM tô **đỏ**; được liệt kê riêng bên dưới).
- Gợi ý cho trang (ví dụ "kiểm tra GE12 → GE112?"); nếu có file `data/processed/soat_anh.md` thì hiện thêm các dòng nhận xét nhắc "trang N" của tài liệu đó.
- Các mục sửa đang có của trang và trạng thái (`de_xuat` / `da_xac_nhan`).

**Thao tác:**

| Nút | Phím | Ý nghĩa |
|---|---|---|
| Đúng | `A` | trang ổn, không cần sửa |
| Không chắc | `U` | đánh dấu xem lại sau |
| Xác nhận mục sửa | — | chuyển mục `de_xuat` của trang sang `da_xac_nhan` |
| Thêm sửa… | — | gõ `find` / `replace` / lý do; kiểm tra `find` khớp **đúng 1 lần** (0 hoặc nhiều lần thì báo lỗi, không lưu); xem trước dòng trước/sau khi sửa |
| force_accept / force_reject | — | dùng lại trang `need_review` / loại trang đang dùng (quay về OCR cũ) |
| ← / → | phím mũi tên | trang trước / sau trong hàng đợi |

Chỉ gõ chữ nhìn thấy trong ảnh; không đoán khi ảnh mờ (bấm **Không chắc**). Ô ghi chú được lưu cùng quyết định.

**Lưu ở đâu:**

- `configs/table_vlm_fixes.yaml`: mỗi mục có thêm `nguoi_soat`, `thoi_gian`, `ghi_chu`. Ghi atomic (file tạm rồi đổi tên); trước mỗi lần lưu bản cũ được sao lưu thành
  `table_vlm_fixes.yaml.<yyyymmdd-hhmmss>.bak` cùng thư mục.
- `data/processed/table_vlm_review_log.jsonl`: mỗi quyết định một dòng (đúng / có sửa / không chắc / accept / reject, người soát, thời gian, hàng đợi, ghi chú).
  Đây là bằng chứng kiểm soát chất lượng cho báo cáo; **không xóa**.
- Nút **Tổng kết** hiện số trang đã duyệt theo hàng đợi, số theo từng kết quả và danh sách mục `da_xac_nhan`; nút *Xuất* ghi `data/processed/table_vlm_review_summary.md`.

Giao diện **không sửa** `data/interim/table_vlm/` hay `data/interim/clean/` và **không chạy lại chunking**. Duyệt xong chạy:

```powershell
python scripts/ingest.py --stage chunk --config all
```

Loader chỉ áp dụng mục `da_xac_nhan` (sửa chuỗi, `force_accept`, `force_reject`); mục `de_xuat` bị bỏ qua. Nếu một mục sửa không còn khớp đúng 1 lần, chunking dừng và báo lỗi.
