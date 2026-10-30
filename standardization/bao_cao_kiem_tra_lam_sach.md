# Báo cáo kiểm tra và làm sạch dữ liệu `crawl_v2`

Tài liệu mô tả việc kiểm tra chất lượng và làm sạch văn bản thu thập từ https://thanglong.edu.vn/vi để xây dựng kho tri thức cho RAG. Mọi con số trong báo cáo được tạo ra bằng chương trình (liệt kê ở mục 7), không nhập tay.

## 1. Tổng quan

### 1.1 Dữ liệu đầu vào

| Hạng mục | Giá trị |
|---|---|
| Số bản ghi | 141 (9 nhóm: chương trình đào tạo 38, lịch thi 21, quy chế 21, học phí 20, chức năng đơn vị 17, kế hoạch đào tạo 10, thông tin liên lạc 7, TKB 5, thông tin sinh viên 2) |
| Bản ghi có file đính kèm đã trích chữ | 82 (81 đầy đủ, 1 một phần); 59 bản ghi không có file đính kèm |
| File đính kèm đã trích chữ | 149 file: 74 PDF có lớp chữ, 72 PDF dạng ảnh phải OCR (2.055 trang), 3 file xlsx |
| Tổng văn bản sau chuẩn hóa | 4.011.465 ký tự (trường `title`, `content`, `extracted_text`) |

Với mỗi bản ghi, `content` là chữ lấy từ website, `extracted_text` là chữ trích từ file đính kèm.

### 1.2 Quy trình

```
crawl (141 bản ghi) -> tải và trích chữ file đính kèm -> OCR 72 file ảnh
   -> sửa lỗi riêng của OCR (fix_ocr.py) -> chuẩn hóa bốn nhóm (normalize.py)
   -> kiểm tra độc lập -> danh sách lỗi còn lại để sửa tay (loi_can_sua.xlsx)
```

### 1.3 Nguyên tắc làm việc

- Kết quả đều do code chạy ra; không tự điền số.
- Không sửa dữ liệu nguồn: mỗi bước ghi ra file riêng và có file đối chiếu từng thay đổi (trước/sau).
- Quy tắc sửa chỉ được thêm khi có số đo làm căn cứ; chỗ nào không đủ căn cứ thì **không sửa** mà đưa vào danh sách sửa tay.
- Sau khi sửa, kiểm tra lại bằng code viết riêng, độc lập với code sửa.

## 2. Phương pháp kiểm tra

| Lớp kiểm tra | Mục đích | Công cụ |
|---|---|---|
| Khám phá dữ liệu gốc | Tìm lỗi trước khi viết quy tắc sửa | `kham_pha_du_lieu.ipynb` (chạy trên `crawl_v2.json`) |
| Kiểm tra đầu ra | Chạy lại đúng các kiểm tra trên dữ liệu đã chuẩn hóa | `kham_pha_du_lieu_clean.ipynb` (chạy trên `crawl_v2_clean.json`) |
| Kiểm tra độc lập | Đếm lại bằng biểu thức riêng, trên cả ba trường văn bản, kể cả chữ từ file đính kèm | script kiểm tra + `phan_tich_du_lieu_ocr_check.ipynb` |
| Kiểm thử quy tắc | Mỗi quy tắc có ca đúng và ca không được đụng; chạy hai lần không đổi thêm (trừ nối dòng, xem mục 6) | `python normalize.py test` (50 ca, đạt cả 50) |
| Đối chiếu mắt | Mở PDF gốc kiểm tra mẫu | xem mục 5.3 |

## 3. Lỗi phát hiện

### 3.1 Nội dung website (`title` + `content`, 141 bản ghi, trước khi sửa)

| Lỗi | Số bản ghi |
|---|---|
| Không ở dạng Unicode NFC | 1 |
| Ký tự vô hình (zero-width, BOM) | 1 |
| Nháy, gạch kiểu Word (`“ ” – —`) | 14 |
| Từ 3 dòng trống liên tiếp trở lên | 4 |
| Nhiều dấu cách liên tiếp | 10 |
| Dòng chỉ có khoảng trắng | 4 |
| Khoảng trắng đầu/cuối dòng | 9 |
| Cùng một từ viết hai kiểu: `kỳ`/`kì` 342/6; `khóa`/`khoá` 18/70 | (toàn bộ nội dung) |

### 3.2 Văn bản trích từ file đính kèm

Các lỗi thuộc bốn nhóm chuẩn hóa. Số liệu đo trước khi viết quy tắc:

- **Ký tự:** nháy/gạch kiểu Word, ký tự lạ do OCR (`¡ ¬ Ñ „ ˆ`…), `(cid:N)` do font PDF.
- **Cấu trúc:** dòng bị PDF ngắt giữa câu; dòng chỉ gồm ký hiệu (đường kẻ); thụt lề thừa; bullet nhiều dạng (`•`, `▪`, `●`).
- **Chính tả:** dấu thanh hai kiểu (`khoá` 597 / `khóa` 1.297 trên toàn bộ văn bản); `kĩ`/`kỹ`, `kì`/`kỳ`.
- **Ngày, số, đơn vị:** ngày không đệm số 0 (`5/9/2025` và `05/09/2025`); khoảng năm có/không dấu cách (`2025-2026`, `2025 - 2026`); số thập phân dùng dấu chấm lẫn dấu phẩy (`3.5 năm`, `3,5 năm`); tiền `đ`/`VND`/`vnđ`/`VNĐ`; `3 TC` lẫn `3 tín chỉ`.

### 3.3 Lỗi riêng của OCR (72 file ảnh)

| Lỗi | Ví dụ | Căn cứ |
|---|---|---|
| Từ tiếng Việt bị dính | `Hệthốngthôngtinkếtoán` | từ lạ có dấu còn 945 trước khi sửa |
| Ký hiệu danh sách bị đọc thành chữ | `s Tên học phần`, `° Học phí` | 264 dòng bắt đầu bằng ký tự lạ |
| Số bị đọc thành chữ `I/l/O` | `l5` thay cho `15` | 492 trường hợp trong chữ OCR, so với 4 trong chữ không qua OCR |
| Mã học phần sai | `ENGII0I` thay cho `ENG1101` | |
| Trang bảng in ngang | cột Mã HP đọc ngược đầu | trang 26 file ACCA (mục 5.3) |
| PDF có lớp chữ nhưng hỏng font | `BQ GIAO DK VA DAO TAO` (tb-2254) | 1 file; đã OCR lại |

## 4. Tổng hợp số thay đổi

### 4.1 Sửa lỗi OCR (`fix_ocr.py`, 72 file, 123.186 dòng)

| Quy tắc | Số dòng đổi |
|---|---|
| Ký hiệu danh sách → `- ` | 237 |
| Tách từ tiếng Việt bị dính | 510 |
| Số lẫn chữ (`l5` → `15`) | 455 |
| Mã học phần sai | 1.234 |
| Danh sách từ biết trước (`E-Leaming` → `E-Learning`) | 3 |

### 4.2 Chuẩn hóa bốn nhóm (`normalize.py`, 141 bản ghi)

| Nhóm | Quy tắc | Số thay đổi | Số bản ghi |
|---|---|---|---|
| 2. Ký tự | NFC | 178 | 14 |
| | ký tự vô hình | 1 | 1 |
| | gạch ngang `–—` → `-` | 3.979 | 66 |
| | nháy cong → nháy thẳng | 1.075 | 16 |
| | `…` → `...` | 15 | 12 |
| | xóa ký tự lạ | 6.540 | 7 |
| 1. Cấu trúc | `(cid:N)` | 18 | 1 |
| | bullet lạ → `- ` | 35 | 7 |
| | danh sách con `  + ` → `- ` | 2 | 1 |
| | bỏ thụt lề (chỉ chữ trích từ PDF) | 1.334 | 20 |
| | khoảng trắng cuối dòng | 570 | 17 |
| | dấu cách liên tiếp | 2.283 | 24 |
| | xóa dòng không có chữ/số | 1.421 | 8 |
| | nối dòng bị ngắt giữa câu | 7.076 | 67 |
| | dòng trống thừa | 9 | 8 |
| 3. Chính tả | đặt lại dấu thanh (`khoá` → `khóa`) | 1.210 | 77 |
| | `kĩ`/`kì`/`kỉ` → `kỹ`/`kỳ`/`kỷ` | 225 | 15 |
| 4. Ngày, số, đơn vị | ngày → `dd/mm/yyyy` (kể cả khoảng ngày `14-17/09/2026`) | 319 | 50 |
| | khoảng năm → `2025 - 2026` | 52 | 19 |
| | thập phân `3.5 năm` → `3,5 năm` | 161 | 24 |
| | `52 %` → `52%` | 17 | 2 |
| | tiền → `VNĐ` | 11 | 7 |
| | `3 TC` → `3 tín chỉ` | 1.124 | 3 |

Tổng số ký tự giảm từ 4.021.975 (bản `crawl_v2_extracted.json`, chữ OCR chưa sửa) xuống 4.011.465 (bản sạch). Hiệu số gồm cả tác động của sửa lỗi OCR và việc OCR lại tb-2254, nên không quy được cho riêng một quy tắc nào.

## 5. Kết quả kiểm tra sau làm sạch

### 5.1 Kiểm tra độc lập: đã đạt (0 chỗ, trên `title`, `content`, `extracted_text`)

Không NFC; ký tự vô hình, điều khiển, `\r`, nbsp; nháy/gạch kiểu Word; khoảng trắng cuối dòng; dấu cách liên tiếp; 3+ dòng trống; thụt lề; `(cid:N)`; dòng không có chữ/số; bullet lạ; dấu thanh kiểu cũ (quét mọi từ); `kĩ`/`kì`/`kỉ`; ngày dùng `-` hoặc `.`; ngày chưa đệm số 0 (còn đúng 1 ngày mất chữ số `05/0/2027`, thuộc lỗi OCR ở mục 5.4); thập phân dùng `.` trước đơn vị; `VND`/`vnđ`; `3 TC`; `52 %`.

`kham_pha_du_lieu_clean.ipynb` chạy lại trên dữ liệu mới không lỗi và báo 0 chỗ còn khớp.

### 5.2 Độ đúng của tách từ dính (kiểm chứng trên chữ chuẩn)

Lấy 200 cụm từ có dấu trong chữ PDF có lớp chữ, ghép dính lại, tách bằng chương trình với từ vựng đã loại chính file chứa cụm đó.

| Kết quả | Số cụm |
|---|---|
| Tách đúng hoàn toàn | 161 (80%) |
| Tách sai | 2 (1%) |
| Không tách, để nguyên | 37 (18%) |

Chương trình ưu tiên ít sai hơn là bao phủ nhiều. Độ đúng này đo trên chữ sạch, không phải trên chữ OCR thật.

### 5.3 Đối chiếu mắt với PDF gốc

| Lỗi | Trang | Kết quả đối chiếu |
|---|---|---|
| `NWSI403` (file Khoa học máy tính) | 7 | PDF in `NWS1403` ở hàng 24 "Mạng máy tính" |
| `IIqzIHVđd` (file ACCA) | 26 | Trang bảng in ngang; ô là hàng 16 "Tài chính doanh nghiệp", mã `FAB1211`; chuỗi rác là mã bị đọc ngược đầu |

Mới đối chiếu 2 trường hợp, chưa đủ để kết luận về độ đúng chung.

### 5.4 Lỗi còn lại: 529 chỗ ở 3 bản ghi

| Nhóm lỗi | tb-2234 | tb-2235 | tb-2284 | Tổng |
|---|---|---|---|---|
| Từ có dấu dính/sai dấu | 248 | 146 | 1 | 395 |
| Mã học phần còn `I/l/O` | 91 | 1 | 0 | 92 |
| Dòng ký tự rời (nhiễu bảng) | 37 | 2 | 0 | 39 |
| Số lẫn chữ | 0 | 2 | 0 | 2 |
| Ngày không hợp lệ (`05/0/2027`) | 0 | 0 | 1 | 1 |
| **Tổng** | **376** | **151** | **2** | **529** |

Cách đo "từ lạ": từ có dấu từ 8 chữ cái trở lên không xuất hiện trong chữ không qua OCR. Tỷ lệ từ (≥3 chữ cái) không có trong từ vựng đó của từng file OCR: tb-2235 10,6%; tb-2234 5,3%; các file OCR còn lại 1,2–2,4%. Lỗi còn lại tập trung ở hai file lớn, chất lượng ảnh thấp.

Trong danh sách có cả chuỗi rác không có "chữ đúng" để sửa (ví dụ `tcrhhhÙéÝ`); với chỗ này đáp án là xóa.

## 6. Hạn chế và điểm chưa kết luận

1. **Nối dòng PDF (7.076 chỗ) chưa có đáp án chuẩn để đo.** Xem mẫu 10 chỗ thì 9 đúng, 1 nối nhầm giữa hai hàng bảng. Quy tắc dựa vào độ dài dòng nên chạy lần hai trên chính đầu ra sẽ nối thêm; chương trình luôn chạy từ dữ liệu gốc nên không bị ảnh hưởng. Có thể tắt bằng `--skip 1.rewrap`.
2. **Thứ tự đọc trong bảng chưa dựng lại** (khoảng 194 trang dạng bảng). Cần OCR có tọa độ từ. Trang ma trận in ngang còn cột Mã HP đọc ngược; trên trang 26 chỉ một số ô bị gắn cờ, các ô khác cùng cột vẫn có thể sai nhưng chưa được đo.
3. **Sai dấu do OCR** (ví dụ `phân` thay cho `phần`) chưa xử lý: cần từ điển, và thử nghiệm sơ bộ cho thấy gợi ý tự động dễ sai (`tỉnh` → `tính`).
4. **Chuẩn dấu thanh là quyết định cần xác nhận.** Chương trình chọn `khóa/hòa/hóa` vì chiếm đa số trên toàn bộ văn bản (`khoá` 597 so với `khóa` 1.297). Riêng nội dung website thì ngược lại: `khoá` 70, `khóa` 18. Đổi sang kiểu `khoá` chỉ cần sửa một hàm.
5. **Danh sách lỗi còn lại không phải mẫu ngẫu nhiên**, nên không dùng để suy ra tỷ lệ lỗi OCR chung. Muốn biết tỷ lệ này cần thêm mẫu ngẫu nhiên có đối chiếu file gốc.
6. **Nhầm `rn` → `m`** chỉ sửa theo danh sách 3 từ biết trước.
7. **Bản ghi tb-2281** có một file ở máy chủ media (lỗi HTTP 500) nên chỉ trích được một phần.
8. **Dữ liệu cá nhân:** các file xlsx danh sách sinh viên (tb-2278, tb-2296, tb-2297) chưa được loại khỏi kho; cần quyết định trước khi đưa vào RAG.

Hai kết luận ban đầu đã bị bác bỏ khi kiểm tra và không dùng trong báo cáo: "518 chuỗi chữ rời bị tách" (phần lớn là dấu `X`/`R` trong ma trận đối chiếu, không phải chữ bị tách) và "209 từ dính" (phần lớn là từ tiếng Anh hợp lệ).

## 7. Cách chạy lại và sản phẩm

| Mục đích | Lệnh hoặc file |
|---|---|
| Sửa lỗi riêng của OCR | `python fix_ocr.py run` → `extract/text_fixed/` |
| Chuẩn hóa bốn nhóm | `python normalize.py run` → `data/crawl_v2_clean.json` |
| Kiểm thử quy tắc | `python normalize.py test` |
| Kiểm chứng tách từ | `python fix_ocr.py validate` |
| Đối chiếu từng thay đổi | `extract/fix_changes.csv`, `extract/normalize_changes.csv`, `extract/normalize_log.csv` |
| Kiểm tra dữ liệu sạch | `notebooks/kham_pha_du_lieu_clean.ipynb` |
| Danh sách lỗi còn lại | `notebooks/phan_tich_du_lieu_ocr_check.ipynb` → `extract/loi_can_sua.csv`, `data/loi_can_sua.xlsx` |

Chương trình OCR lại một file có lớp chữ hỏng: `python ocr_scans.py run --file-key <khóa file> --force`.

## 8. Hướng giải quyết tiếp theo

| Việc | Cách làm | Ghi chú |
|---|---|---|
| Sửa tay 529 chỗ | Điền cột "Khắc phục" trong `data/loi_can_sua.xlsx` (sheet "Hướng dẫn" có ví dụ), sau đó viết bước áp dụng vào dữ liệu | Chưa viết bước áp dụng |
| Sửa mã học phần ở trang ma trận | Ghép tên môn (đọc đúng) với mã đúng trong bảng khung chương trình | Cần kiểm chứng trên mẫu trước |
| Dựng lại bảng | OCR có tọa độ từ, dựng hàng cột, so với PDF có lớp chữ để kiểm chứng | Chưa làm |
| Đo tỷ lệ lỗi OCR thật | Lấy mẫu ngẫu nhiên, đối chiếu file gốc | Chưa làm |
| Bước sau làm sạch | Chunking, gắn metadata, xây kho tri thức | Chưa làm |
