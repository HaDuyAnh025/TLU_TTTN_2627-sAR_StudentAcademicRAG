# Trích xuất text + OCR toàn bộ dữ liệu trên máy thuê GPU (Ubuntu)

Nguyên tắc: mọi kết quả đều do chương trình tạo ra, giữ nguyên đầu ra gốc ("raw"), có mã băm niêm phong.
Không sửa tay file kết quả; muốn đổi thì chạy lại chương trình.

**Nhớ đặt hạn mức chi tiêu đủ (khoảng 35.000đ) và tắt/xóa máy khi xong để dừng tính tiền.**

## 0. Trên máy Windows: đóng gói (tại thư mục `sAR`)
```powershell
python deploy/pack.py          # tạo ..\sar_gpu_pack.zip (dữ liệu + mã, đường dẫn dùng '/')
```

## 1. Gửi lên máy thuê (PowerShell; thay CỔNG và IP theo trang quản lý)
```powershell
$K = "$env:USERPROFILE\.ssh\sar_gpu"
scp -i $K -P CỔNG ..\sar_gpu_pack.zip root@IP:/root/
ssh -i $K -p CỔNG root@IP "nvidia-smi; df -h /"
```

## 2. Trên máy thuê: giải nén và cài đặt (BẮT BUỘC chạy bằng nohup, SSH có thể bị ngắt)
```bash
apt-get update -qq && apt-get install -y -qq unzip
mkdir -p ~/sAR && unzip -q ~/sar_gpu_pack.zip -d ~/sAR && cd ~/sAR
nohup bash deploy/setup_ubuntu.sh > /root/setup.log 2>&1 &
tail -f /root/setup.log        # chờ thấy dòng "cuda True" và "XONG"; Ctrl+C để thoát xem log
```

## 3. Chạy thử 2 file để chắc chắn mọi thứ ổn (khoảng 1 phút)
```bash
cd ~/sAR && source .venv/bin/activate
python scripts/ingest.py --stage extract --base-engine vietocr:vgg_transformer --limit 2
python scripts/ingest.py --stage verify    # sẽ báo thiếu kết quả của các file chưa chạy, đó là bình thường
```

## 4. Chạy toàn bộ (3 tiến trình song song, chạy nền)
```bash
for i in 0 1 2; do
  setsid nohup env PYTHONUNBUFFERED=1 python scripts/ingest.py --stage extract \
    --base-engine vietocr:vgg_transformer --shard $i/3 > /root/extract_$i.log 2>&1 < /dev/null &
done
grep -h "^\[" /root/extract_*.log | tail -5       # xem tiến độ
```
Chạy lại cùng lệnh sẽ bỏ qua file đã xong (khớp mã băm và niêm phong), nên ngắt giữa chừng không mất gì.

## 5. Sao lưu kết quả về máy bạn định kỳ (mỗi ~15 phút, PowerShell)
```powershell
scp -r -i $K -P CỔNG root@IP:/root/sAR/data/interim/extract .\data\interim\
```

## 6. Khi xong: kiểm chứng ngay trên máy thuê, rồi tải về
```bash
python scripts/ingest.py --stage verify     # phải ra "KẾT QUẢ: ĐẠT"
```
Rồi tải bản cuối về (lệnh ở bước 5), chạy lại `verify` trên máy bạn để chắc chắn dữ liệu đến nơi nguyên vẹn,
**sau đó tắt/xóa máy trên trang quản lý** và xác nhận đã dừng tính tiền.

## Cấu trúc kết quả (`data/interim/extract/<tên file>.json`, kèm `.json.sha256`)
- Mức file: `input_sha256`, `source` (tiêu đề/nguồn lấy nguyên từ crawl), `pipeline` (công cụ, phiên bản, thiết bị, ngưỡng).
- Mỗi trang: `route` (`text_layer` hoặc `ocr`) và `route_reason`; `features`; **`raw`** (đầu ra gốc);
  `derived` (văn bản/khối bảng, tính từ `raw` bằng quy tắc cố định); `quality` (cờ chất lượng, chỉ là thông tin kèm theo);
  `error` (nếu trang lỗi).
- `verify` kiểm tra: đủ file, khớp mã băm đầu vào, đủ số trang, không trang lỗi, `derived`/`quality` khớp tính lại từ `raw`,
  và file không bị sửa sau khi ghi.
