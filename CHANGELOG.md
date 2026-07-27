# Changelog

## v0.1.1

- Sửa workflow đỏ khi player API HTTP 200 nhưng không có stream trong giờ yên.
- Giữ last-good và luôn trả exit code 0 cho kết quả rỗng hợp lệ.
- Mở rộng parser nhiều dạng payload/purl.
- Ghi thêm chẩn đoán cấu trúc payload vào debug JSON.
- Seed `sptv.m3u` bằng 41 FLV thật từ playlist tham chiếu do người dùng cung cấp.
- Audit hỗ trợ `--allow-empty`.
- Không thêm cron GitHub, không probe media CDN.
