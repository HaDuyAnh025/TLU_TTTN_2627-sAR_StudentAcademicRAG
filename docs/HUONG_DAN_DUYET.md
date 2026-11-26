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


## 9. Duyệt bộ câu hỏi đánh giá retrieval — `scripts/review_testset.py`

Bộ câu hỏi (`data/eval/questions.jsonl`) dùng để **chốt cấu hình retrieval** (có rerank không, `fusion_w`, `n_rerank`, ngưỡng từ chối). Câu sai đáp án làm sai cả kết luận,
nên mỗi câu cần một người đọc kỹ. Đáp án của mỗi câu là **đoạn văn bản (span)** trong tài liệu, không phải chunk.

### 9.1 Mở giao diện

```powershell
python scripts/review_testset.py --reviewer "Tên bạn"
```

- Mở `http://127.0.0.1:8770` (bận thì tự đổi cổng). Chỉ máy bạn truy cập được; không cần khóa API. Dừng: `Ctrl+C`.
- **Nhiều người**: mỗi người một bản sao repo và một hàng đợi riêng, ví dụ người thứ 2 trong 3 người: `--shard 2/3`. Câu được chia theo thứ tự id nên không trùng giữa các người.
  Duyệt xong gửi file `data/eval/questions.jsonl` của bạn; người phụ trách gộp bằng `python scripts/gen_testset.py --merge <file của từng người>`
  (mỗi câu lấy bản đã duyệt mới nhất; câu bạn tự thêm có id `qh_<tên>_NNN` nên không đụng id người khác).
- Mọi thay đổi được ghi ngay (atomic) vào `questions.jsonl`, bản cũ lưu thành `questions.jsonl.<thời gian>.bak`; nhật ký từng thao tác ở `data/eval/questions_review_log.jsonl` (**không xóa**).

### 9.2 Tab "Duyệt câu"

Bên trái là hàng đợi (lọc theo `doc_type` và trạng thái, mặc định "chưa duyệt"). Bên phải: câu hỏi, câu trả lời tham chiếu, các span đáp án, và **văn bản tài liệu quanh span** (span tô vàng).

Với mỗi câu, tự hỏi:
1. Câu hỏi có **tự đứng được** (không cần xem tài liệu mới hiểu) và giống cách sinh viên thật hỏi không?
2. Đáp án tham chiếu có **đúng** theo văn bản không? Các span có **đủ** để trả lời, không thừa không thiếu?
3. Câu có trả lời được bằng **kiến thức chung** không cần tài liệu không? (Nếu LLM đã đánh dấu, phải tích xác nhận mới chấp nhận được.)
4. Có **tên người thật** không? (Có thì sửa thành tên giả hoặc Loại.)
5. Câu phụ thuộc khóa: `user_ctx.khoa` và phiên bản (hiện ở nhãn vàng) có khớp với tài liệu không?
6. Độ trùng từ cao (nhãn đỏ > 0,7): câu hỏi chép gần nguyên văn tài liệu, kết quả sẽ thiên về BM25 — nên viết lại cho tự nhiên hơn hoặc Loại.

Thao tác (có phím tắt khi con trỏ không nằm trong ô nhập):
- **Chấp nhận** `A`: giữ nguyên. Nếu bạn đã sửa chữ/span/loại trước đó thì trạng thái tự thành `edited`.
- **Lưu bản sửa** `E`: sửa câu hỏi, câu trả lời, loại, khóa, hành vi, rồi lưu.
- **Chọn lại span**: kéo chuột chọn đoạn trên văn bản → bấm *+ Thêm vùng chọn làm span mới*, hoặc bấm *chọn* ở một span rồi *Thay span đang chọn bằng vùng chọn*. Chọn **ngắn nhất có thể** nhưng đủ ý
  (một câu, một Khoản, hoặc một dòng bảng). Câu loại `nhieu_doan` cần ≥ 2 span. *Mở rộng ±* / *Toàn văn* để xem thêm ngữ cảnh.
- **Loại** `R`: chọn lý do (sai đáp án, mơ hồ, chép nguyên văn, kiến thức chung, trùng, có tên thật, không thực tế…).
- **Không chắc** `U`: câu vẫn nằm trong hàng đợi chưa duyệt, để hỏi người khác. Nhớ ghi chú.
- `J`/`K` (hoặc ←/→): câu sau / câu trước.

### 9.3 Tab "Ngoài phạm vi"

Duyệt các câu mà hệ thống **phải từ chối** (không liên quan; cùng lĩnh vực nhưng kho không có; hỏi thông tin cá nhân sinh viên với tên giả; dễ gây nhầm). Bấm **Chạy thử retrieval** để xem 5 đoạn hybrid trả về:
- Nếu kho **thực sự có** câu trả lời → *Loại* với lý do "kho có câu trả lời" (câu đó không còn là câu ngoài phạm vi).
- Nếu các đoạn trả về chỉ gần chủ đề nhưng không nói điều được hỏi → *Chấp nhận*.
- Câu hỏi thông tin cá nhân phải dùng tên giả rõ ràng (Nguyễn Văn A, Trần Thị B…); **không đưa tên thật** vào bất kỳ câu nào.

Nút chạy thử cần Qdrant đang chạy và khóa OpenAI (để embedding câu hỏi). Không có thì UI báo lỗi, các chức năng khác vẫn dùng được.

### 9.4 Tab "Thêm câu người viết" (20 câu / cả nhóm)

Viết câu hỏi **như sinh viên thật hỏi** (lấy ý từ câu hỏi thường gặp, nhóm Facebook lớp; có thể viết tắt K38, HK1, TC, CTĐT, hoặc không dấu):
1. Gõ câu hỏi và câu trả lời ngắn; chọn loại; nhập khóa nếu câu phụ thuộc khóa.
2. Tìm tài liệu (lọc theo loại, gõ một phần tiêu đề), bấm vào để mở toàn văn.
3. **Kéo chuột chọn đoạn đáp án**, bấm *+ Thêm vùng chọn làm span*; câu cần 2 chỗ thì thêm 2 span.
4. *Lưu câu hỏi*. UI báo độ trùng từ; nếu > 0,7 nên diễn đạt lại.

Câu người viết được ghi `created_by: human`, trạng thái `accepted`. Cần cả người đọc lại thì nhờ người khác mở lại câu đó trong tab *Duyệt câu* (bộ lọc "tất cả").

### 9.5 Tab "Tổng kết"

Số câu theo trạng thái × `doc_type` × `type`, phân bố độ trùng từ, số câu dev/test, số câu phụ thuộc khóa và câu người viết. Nút *Xuất* ghi `data/eval/questions_summary.md`.
Mục tiêu sau duyệt: ~100 câu có đáp án (quy chế 25, CTĐT 15, học phí 15, lịch thi + TKB 10, kế hoạch 10, thông báo 15, còn lại 10), ~20 câu ngoài phạm vi, ≥ 10 câu phụ thuộc khóa
kèm 5 câu cùng nội dung không có khóa, 20 câu người viết.

### 9.6 Sau khi duyệt xong (người phụ trách)

```powershell
python scripts/gen_testset.py --merge <các file questions.jsonl của từng người>    # nếu nhiều người
python scripts/gen_testset.py --split                                              # chia 30% dev / 70% test, phân tầng theo type và doc_type, seed 42
python scripts/eval_retrieval.py                                                   # chấm trên DEV
```

**Không chỉnh tham số theo kết quả trên tập test**; tập test chỉ chạy một lần cuối (`--split test --final`).
