# Quy trình chuyển PDF và ảnh thành văn bản Markdown

Viết lại theo đúng những gì code đang làm (cập nhật 2026-11-20). Mọi lệnh chạy qua `python scripts/ingest.py --stage <tên>`.

## 0. Nguyên tắc
1. **Kết quả do chương trình tạo ra.** Không sửa tay vào file kết quả, không chèn đáp án tay. Muốn sửa phải đi qua lớp hiệu chỉnh (mục 5).
2. **Mỗi bước ghi ra thư mục riêng, bước sau không ghi đè bước trước.** `extract` (OCR gốc) không bao giờ bị sửa. Mọi sửa nằm ở lớp khác, văn bản sạch là kết quả tính ra từ chúng.
3. **Có mã băm niêm phong và lệnh verify** ở các bước chính, để phát hiện file bị sửa tay.
4. **Văn bản do mô hình sinh (LLM/VLM) chỉ được dùng sau khi qua kiểm tra**, và luôn ghi riêng nguồn, mô hình, thời điểm.
5. Bỏ qua theo quyết định: 30 file đính kèm tải lỗi HTTP 500, và các trang crawl không có file đính kèm.

## 1. Sơ đồ tóm tắt: OCR → so sánh → đánh giá → phân nhánh → label → clean

```
PDF / ảnh
  ├─ có lớp chữ PDF ───────────────────────────────────────────► clean (lấy nguyên văn)
  └─ scan / ảnh
       │  OCR 1: VietOCR (đọc chữ)
       │  OCR 2: RapidOCR (chỉ đối chiếu số)
       ▼
   SO SÁNH hai OCR (chuỗi số khác nhau, độ tin cậy, DPI, bảng, ký tự lạ)
       ▼
   ĐÁNH GIÁ CHẤT LƯỢNG → gắn cờ
       ├─ THẤP (có cờ, 623 trang)
       │     LLM đối chiếu ảnh → Labelling (corrections-ui)
       ├─ CAO (không cờ, 456 trang)
       │     rescan: 5 luật + LLM đối chiếu ảnh → Labelling (rescan-ui)
       └─ BẢNG chương trình đào tạo (chọn riêng, bất kể cao/thấp)
             VLM đọc lại trang → Labelling (table-vlm-review-ui)
       ▼
   CLEAN (OCR gốc + sửa đã duyệt + sửa chữ/dấu an toàn) → chunk
```

**Khác với sơ đồ ban đầu ở hai điểm**, nêu rõ để bạn quyết định giữ hay đổi:
1. Pipeline hiện **không** chuyển trang chất lượng cao sang VLM. Trang cao đi qua rescan (luật + LLM), và VLM chỉ dùng cho trang bảng của chương trình đào tạo.
2. VLM chưa dùng cho nhóm chất lượng thấp, vì bạn đã quyết định VLM chỉ chạy sau bước đánh giá và khi bạn đồng ý.

## 1b. Sơ đồ đầy đủ các bước

```
data/raw/files (PDF, ảnh)
  │ [1] extract            lớp chữ PDF hoặc OCR  → data/interim/extract/*.json  (raw / derived / quality)
  │ [2] verify, evaluate   kiểm mã băm, gắn cờ chất lượng → data/eval/extract_report.md
  │ [3] llm-review         LLM đối chiếu ảnh gốc, tìm chỗ nghi sai
  │ [4] corrections-build  LLM tự sửa chỗ đủ điều kiện, còn lại chờ người
  │ [5] corrections-ui     người duyệt từng chỗ → data/interim/corrected (623 trang bị gắn cờ)
  │     rescan-*           rà soát 456 trang không cờ → data/interim/corrected_rescan
  │     relabel-*          duyệt lại chỗ đã duyệt nhưng chưa thay vào văn bản được
  │ [6] clean              chọn văn bản dùng được → data/interim/clean/*.json
  │ [7] table-vlm (tùy chọn) VLM đọc lại trang chương trình đào tạo có bảng → data/interim/table_vlm
  ▼ [8] chunk              → data/processed/chunks/*.jsonl  (đã chốt, xem FROZEN.md)
```

## 2. Bước 1 — Trích xuất (`extract`)
Mỗi trang đi theo một trong hai đường:

| Đường | Điều kiện | Cách làm |
|---|---|---|
| `text_layer` | PDF có lớp chữ, từ 50 ký tự trở lên (`text_layer_min_chars`) | Lấy chữ trực tiếp bằng PyMuPDF, không OCR |
| `ocr` | Ảnh, hoặc PDF scan | Dựng trang thành ảnh 200 DPI, dò và xoay về thẳng (thử 0/90/180/270), OCR nền bằng VietOCR (`vgg_transformer` trên GPU, `vgg_seq2seq` trên CPU) |

Với trang OCR có từ 8 chuỗi số trở lên, chạy thêm RapidOCR (PP-OCRv5) chỉ để **đối chiếu số** với OCR nền.

Từ kết quả thô, chương trình tính ra văn bản trang: gom từ thành dòng, nhận dạng bảng và xuất thành bảng Markdown với dấu `|`. Bước tính này là hàm xác định của dữ liệu thô nên tính lại được.

Mỗi file ghi thành `data/interim/extract/<tên>.json` (schema 2) gồm 3 phần:
- `raw`: kết quả gốc của công cụ, giữ nguyên.
- `derived`: văn bản Markdown của trang.
- `quality`: các cờ chất lượng.

Chạy lại được: file nào đã xong và khớp mã băm thì bỏ qua; trang lỗi được ghi `error` và làm lại ở lần sau.

```
python scripts/ingest.py --stage extract
python scripts/ingest.py --stage extract --base-engine vietocr:vgg_transformer --shard 0/3   # GPU, chia 3 tiến trình
python scripts/ingest.py --stage extract --files drive-1ABC --limit 3                         # chạy thử
```

## 3. Bước 2 — Kiểm chứng và đánh giá
```
python scripts/ingest.py --stage verify     # đầy đủ, khớp mã băm, không bị sửa tay
python scripts/ingest.py --stage evaluate   # thống kê → data/eval/extract_report.md
```
Cờ chất lượng gắn cho trang (ngưỡng ở `configs/ocr.yaml`, mục `flags`): `low_dpi`, `low_conf`, `number_mismatch`, `table_suspected`, `low_text`, `garbled`. Trang OCR có cờ là 623 trang, trang OCR không cờ là 456 trang.

## 4. Bước 3–4 — LLM rà soát và tự sửa
```
python scripts/ingest.py --stage llm-review --scope flagged
python scripts/ingest.py --stage corrections-build
```
- LLM (gpt-5.4-mini, ảnh `detail: high`) đối chiếu từng đoạn OCR với ảnh gốc, trả về danh sách chỗ nghi sai kèm phân loại: `chu_dau`, `so_lieu`, `bang`, `thieu_dong`, `thua_dong`, `khac`.
- LLM chỉ **tự sửa** khi đủ các điều kiện trong `configs/ocr.yaml` (mục `corrections`): độ chắc chắn cao, đoạn gốc khớp nguyên văn đúng 1 lần, chuỗi số phải trùng RapidOCR, độ dài sau sửa không bất thường. Chỗ không đủ điều kiện chờ người.
- Kết quả ghi ở **lớp hiệu chỉnh** `data/interim/corrected`, mỗi mục có trạng thái (`applied`, `human_applied`, `pending_human`, `unapplicable`, `no_change`, `reverted`), gắn `human_checked` khi người đã duyệt.

## 5. Bước 5 — Người duyệt
```
python scripts/ingest.py --stage corrections-ui                    # giao diện: văn bản gốc | LLM sửa | Đúng/Sai | gõ lại
python scripts/ingest.py --stage corrections-ui --part 2/3         # chia phần cho nhiều người
python scripts/ingest.py --stage corrections-merge --from <thư mục corrected của người kia>
python scripts/ingest.py --stage corrections-verify
```
Ba nhánh phụ:
- **Trang không cờ (rescan):** `rescan-hints` (5 luật không tốn API) → `rescan-llm` (LLM đối chiếu ảnh) → `rescan-build` → `rescan-ui` → lớp riêng `data/interim/corrected_rescan`. Kiểm mẫu 80 trang trước khi rescan cho 18,8% dòng sai (CI 15,5–22,5%). Chưa đo lại độc lập sau rescan.
- **Duyệt lại chỗ không thay vào văn bản được:** `relabel-build` → `relabel-ui` → `relabel-merge`. Chỗ nào người đã duyệt mà đoạn gốc không khớp, lặp hoặc chồng lấn thì được đưa ra duyệt lại theo cả dòng.
- **Kiểm mẫu:** `audit-build`, `audit-ui` để chấm mẫu theo từng dòng.

## 6. Bước 6 — Làm sạch (`clean`)
```
python scripts/ingest.py --stage clean
python scripts/ingest.py --stage clean-verify
```
Văn bản sạch cho mỗi trang:

| Loại trang | Văn bản lấy |
|---|---|
| `text_layer` | Nguyên văn `derived.text` |
| OCR, không có lớp hiệu chỉnh | OCR gốc |
| OCR, có lớp hiệu chỉnh | OCR gốc + các sửa **người đã duyệt** còn hiệu lực + sửa **LLM chưa duyệt** chỉ khi thỏa tất cả: loại `chu_dau`, giữ nguyên mọi chuỗi chữ số, giữ nguyên số dấu `|`, không xuống dòng, không có cảnh báo số liệu hoặc cấu trúc bảng |

Chỉ làm sạch ký tự ở mức an toàn: Unicode NFC, bỏ ký tự điều khiển và ký tự độ rộng 0, bỏ khoảng trắng cuối dòng. Kết quả ở `data/interim/clean/<tên>.json` kèm `.sha256` và `_manifest.json`.

Căn cứ của chính sách: ở phần đã duyệt, loại `chu_dau` bị người bác khoảng 7%, các loại khác bị bác 19–80%. Chính sách chỉnh ở `ADOPT_UNREVIEWED` trong [cleaner.py](../src/rag/ingestion/cleaner.py); khi có thêm bản duyệt thì chạy lại `clean` là tự dùng bản duyệt.

## 7. Bước 7 — Đọc lại bảng bằng VLM (tùy chọn)
Dành cho các trang chương trình đào tạo nghi có bảng, ghi riêng ở `data/interim/table_vlm/<doc_id>.json`, không ghi đè `clean`.
- Mỗi trang có kiểm tra tự động; trang `need_review` không được dùng cho tới khi người duyệt.
- Duyệt bằng `python scripts/ingest.py --stage table-vlm-review-ui`, quyết định ghi vào `configs/table_vlm_fixes.yaml` (kèm bản sao `.bak` và nhật ký).
- Đã duyệt 75 trang: đúng 68, có sửa 7. Ước lượng độ đúng của VLM chỉ có mẫu ngẫu nhiên 10 trang, đúng 8 (khoảng tin cậy 95% là 0,49–0,94), nên rất rộng.

## 8. Bước 8 — Chunking
```
python scripts/ingest.py --stage chunk --config all     # c1, c2, c3
```
Đọc `data/interim/clean` (và lớp VLM nếu `use_table_vlm: true`) cùng `configs/doc_meta.yaml`, ghi `data/processed/chunks/*.jsonl` và `stats.json`. Bộ chunk hiện tại đã chốt, xem [FROZEN.md](../data/processed/chunks/FROZEN.md); không chạy lại cho tới khi embedding báo xong.

## 9. Về định dạng `.md`
Hiện tại **Markdown nằm bên trong các file JSON** (`derived.text` ở extract, `text` ở clean), bảng viết bằng dấu `|`. Pipeline chưa xuất ra từng file `.md` riêng cho mỗi tài liệu. Nếu cần (để đọc hoặc nộp), thêm một bước `export-md` ghép các trang của `clean` thành `data/processed/md/<tên>.md`, mỗi trang ngăn bằng một dòng chú thích nguồn và số trang.

## 10. Việc còn mở
- Bản label phần 1/2 của lớp 623 trang chưa nhận. Khi có: `corrections-merge --from …`, rồi `clean`, rồi kiểm tra xem có cần chunk lại hay không.
- 21 mục mảnh chữ con dấu, 1 mục `tự đánh giá:`, 1 trang JSON lỗi (`drive-1Hj9q0nJUetMG5e2i9yCmX4Cw7F-muKCv-p1`) chưa xử lý.
- Khoảng 61 chỗ số/mã không đặt được vào văn bản (đã quyết định bỏ qua).
- Tỷ lệ lỗi sau rescan chưa đo độc lập.
