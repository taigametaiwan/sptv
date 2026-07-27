# SPTV API GitHub v0.1.0

Bộ source lấy lịch và URL FLV SPTV qua API, tối ưu theo hướng **ít request** và không thăm dò video CDN.

## Cơ chế

1. Mở trang chủ đúng một lần để tạo cookie/session.
2. Lấy `data/zb.json` đúng một lần.
3. Lọc trận trong cửa sổ thời gian.
4. Gọi `ajax_zb.php?act=player...` **tuần tự**, mặc định chờ ngẫu nhiên 4,0–5,5 giây giữa hai trận.
5. Chỉ đọc `purl[].url`; không gửi Range, không tải đầu file FLV, không thử 5 bộ header.
6. Trường số đầu tiên trong `auth_key` được ghi là `signed_at` để chẩn đoán, **không coi là thời điểm hết hạn**.
7. Nếu lượt mới có 0 link thật thì giữ nguyên `sptv.m3u` cũ.
8. Gặp 403/429 liên tiếp hai lượt thì dừng sớm.

Cơ chế này được suy ra từ playlist tham chiếu: các dấu thời gian `auth_key` của 41 link tăng đều khoảng 2–7 giây, trung bình gần 5 giây, phù hợp với việc gọi player API tuần tự. Source riêng của repo tham chiếu không công khai nên không thể khẳng định từng dòng code giống hệt.

## Chạy trên máy tính

Windows: chạy `run_local.bat`.

Linux/VPS:

```bash
chmod +x run_local.sh
./run_local.sh
```

## Đưa lên GitHub

1. Tạo repository mới và tải toàn bộ source lên.
2. Mở tab **Actions**.
3. Chạy workflow **Update SPTV playlist** thủ công.
4. File kết quả là `sptv.m3u` tại thư mục gốc.

Workflow chỉ có `workflow_dispatch` và `repository_dispatch`; **không có cron nội bộ**. Có thể dùng cron bên ngoài gửi `repository_dispatch`, nhưng nên bắt đầu với tần suất thấp thay vì 5 phút/lần.

## Biến cấu hình

Sao chép `.env.example` sang `.env` khi chạy cục bộ, hoặc đặt trong phần `env` của workflow. Script đọc trực tiếp biến môi trường; file `.env` không tự nạp để tránh thêm dependency.

Các biến quan trọng:

- `SPTV_DELAY_MIN_SECONDS=4.0`
- `SPTV_DELAY_MAX_SECONDS=5.5`
- `SPTV_STOP_AFTER_DENIALS=2`
- `SPTV_MIN_REAL_STREAMS=1`
- `SPTV_EMIT_HEADERS=0`
- `SPTV_INCLUDE_PLACEHOLDERS=0`

## Audit

```bash
python -m unittest discover -s tests -v
python audit_m3u.py sptv.m3u --strict
```

`audit_m3u.py` không gọi mạng. Nó đếm link FLV, placeholder, URL lỗi, đường dẫn trùng và thống kê nhịp timestamp trong `auth_key`.

## Lưu ý

- Không có proxy video, không tiêu tốn băng thông phát của GitHub runner/VPS.
- Không bảo đảm CDN sẽ cho mọi IP/ASN truy cập. GitHub Actions có thể bị CDN từ chối theo từng thời điểm.
- Dùng nguồn và luồng mà bạn có quyền truy cập; URL của bên thứ ba có thể thay đổi hoặc ngừng hoạt động.

## Khác biệt quan trọng so với VPS Scanner v0.3.11

Bản VPS cũ hiểu `auth_key[0]` là expiry, nên mỗi trận thường gọi player API lần thứ hai và cuối cùng vẫn có thể loại URL vì “TTL dưới 120 giây”. Bản này bỏ hoàn toàn giả định TTL đó. Nó cũng không có cron 5 phút và không thử năm profile HTTP vào mỗi FLV.
