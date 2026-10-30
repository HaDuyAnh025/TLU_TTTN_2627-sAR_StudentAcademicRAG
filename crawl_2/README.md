# crawl_2 — Crawl dữ liệu học vụ / đào tạo Trường ĐH Thăng Long

Thu thập dữ liệu từ https://thanglong.edu.vn/vi để phục vụ RAG: chương trình đào tạo, quy chế, lịch thi, kế hoạch, học phí, TKB, thông tin liên lạc và chức năng các đơn vị.

## Cấu trúc thư mục

```
crawl_2/
├── crawl_v2.py        # chương trình crawl
├── crawl_v2.csv       # kết quả (UTF-8 có BOM, mở được bằng Excel)
├── crawl_v2.json      # kết quả (cùng dữ liệu, links/curriculum dạng danh sách)
├── README.md
└── data/raw_api/      # bản lưu phản hồi API (cache), chạy lại không gọi lại API
```

## Cách chạy lại

Yêu cầu: Python 3.8+, **không cần cài thư viện** (chỉ dùng thư viện chuẩn).

```bash
cd crawl_2
python crawl_v2.py
```

- Chạy lần đầu hoặc sau khi xoá `data/raw_api/`: script gọi API, nghỉ 1 giây giữa mỗi request, mất khoảng 3–5 phút.
- Chạy lại khi cache còn: gần như tức thì, chỉ tải lại `sitemap.xml` và 1 trang HTML để lấy danh sách ngành.
- **Lấy dữ liệu mới** (thông báo mới đăng): xoá `data/raw_api/` (hoặc chỉ các file `ann_*.json`) rồi chạy lại.
- Windows nếu lỗi hiển thị tiếng Việt: `python -X utf8 crawl_v2.py`.

Kết quả ghi đè `crawl_v2.csv` và `crawl_v2.json` trong cùng thư mục.

## Nguồn dữ liệu

Website tải nội dung từ API công khai của chính trường (không cần đăng nhập). Script chỉ gọi GET, chỉ các endpoint mà frontend của trang dùng:

| Endpoint (`https://api-cms.thanglong.edu.vn/api/v1`) | Dùng cho |
|---|---|
| `/announcements/{id}` | Thông báo, quyết định (id lấy từ `sitemap.xml`, hiện 2222–2321) |
| `/pages/code/{mã}` | Trang CMS: ngành học, Cơ cấu tổ chức, Liên hệ, Đào tạo, ... |

Lưu ý: `robots.txt` của `thanglong.edu.vn` cấm `/api/` trên host chính; host `api-cms` không có `robots.txt`. Đây không phải API được trường công bố cho bên thứ ba nên có thể thay đổi bất kỳ lúc nào. Nếu dùng cho mục đích chính thức, nên xin phép nhà trường. Có thể chỉnh `DELAY` trong `crawl_v2.py` để nghỉ lâu hơn giữa các request.

## Kết quả (lần chạy ngày 2026-10-28): 141 bản ghi

| `category` | Số lượng | Nguồn |
|---|---|---|
| `chuong_trinh_dao_tao` | 38 | 25 trang ngành (kèm danh sách môn theo năm trong `curriculum`) + các quyết định về chương trình đào tạo |
| `lich_thi` | 21 | Thông báo |
| `hoc_phi` | 20 | Thông báo (bảng học phí từng ngành nằm trong trang ngành) |
| `quy_che` | 21 | Đăng ký học, bảo vệ, chuyển ngành, tốt nghiệp, chuẩn đầu ra |
| `ke_hoach_dao_tao` | 10 | Thông báo |
| `tkb` | 5 | Thay đổi phòng học, dạy bù |
| `chuc_nang_don_vi` | 17 | Từng phòng ban/khoa từ trang Cơ cấu tổ chức |
| `thong_tin_lien_lac` | 7 | Email, điện thoại từng đơn vị từ trang Liên hệ |
| `thong_tin_sinh_vien` | 2 | Trang Sinh viên hiện tại, Tài liệu học tập |
| `mon_thay_the` | 0 | Không có thông báo nào về môn thay thế |

## Các trường dữ liệu

| Trường | Ý nghĩa |
|---|---|
| `id` | Định danh ổn định: `tb-<id thông báo>`, `nganh-<slug>`, `page-<mã trang>`, `unit-<trang>-<tên đơn vị>` |
| `category` | Nhóm nội dung (bảng trên) |
| `content_type` | `announcement`, `major`, `page`, `unit` |
| `title` | Tiêu đề |
| `date` | Ngày đăng (`YYYY-MM-DD`), chỉ có với thông báo |
| `department` | Đơn vị đăng (thông báo), khoa (ngành) hoặc tên đơn vị |
| `content` | Nội dung dạng văn bản |
| `links` | Link PDF/Google Drive, email (`mailto:`), điện thoại (`tel:`). CSV: mỗi link một dòng; JSON: danh sách `{name, url}` |
| `source_url` | Trang gốc trên website |
| `tags` | Tất cả nhóm mà tiêu đề thông báo khớp (nhóm đầu tiên là `category`) |
| `announcement_type` | Loại thông báo trên website (Học vụ, Sinh hoạt, ...) |
| `legacy_url` | Link bài trên website cũ (nếu có) |
| `curriculum` | Chỉ với ngành: môn học theo năm, JSON `[{year, group, subjects[]}]` |
| `crawled_at`, `content_hash` | Thời điểm crawl và hash nội dung (phát hiện thay đổi) |

## Hạn chế

1. **Nội dung thông báo chủ yếu là tiêu đề + link file.** Phần lớn thông báo/quyết định chỉ có file PDF trên Google Drive, nên `content` chỉ là tiêu đề. Script chưa tải và trích chữ từ PDF.
2. **Phân loại thông báo theo từ khóa trong tiêu đề** nên có thể sai ở một số bản ghi. Chỉnh luật trong `ANN_RULES` (`crawl_v2.py`) và chạy lại; cache giúp việc này không tốn request.
3. **Thông báo tuyển sinh, trúng tuyển, nhập học bị loại có chủ đích** (18 thông báo, luật `ANN_EXCLUDE`), vì không thuộc 6 nhóm yêu cầu.
4. **Tên khoa của ngành** lấy từ thẻ ngành nổi bật nên có thể để trống.
5. **Link ảnh cũ** dạng `localhost:18000` được đổi sang `media-cms.thanglong.edu.vn`, chưa kiểm tra mở được hay không.
6. **Tài liệu học tập** chỉ có tiêu đề trang, vì nội dung do trang khác nạp.
7. Chỉ crawl bản tiếng Việt (`/vi/`). Phạm vi thông báo lấy theo `sitemap.xml` (id 2222–2321); thông báo cũ hơn không có trong sitemap.

## Chỉnh nhanh

| Muốn | Sửa trong `crawl_v2.py` |
|---|---|
| Nghỉ lâu hơn giữa các request | `DELAY` |
| Thêm/bớt trang CMS cần lấy | danh sách `PAGES` |
| Đổi cách phân loại thông báo | `ANN_RULES`, `ANN_EXCLUDE` |
| Đổi cột của CSV | danh sách `cols` trong `main()` |
