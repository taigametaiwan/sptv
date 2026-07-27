# Changelog

## v0.1.3

- Thêm cron GitHub `*/5 * * * *` theo yêu cầu.
- Hạ `SPTV_MIN_TTL_SECONDS` từ 900 xuống 300 sau khi log xác nhận key hợp lệ chỉ còn khoảng 600 giây.
- Đổi concurrency thành `cancel-in-progress: false` để lượt đang chạy không bị cron kế tiếp hủy.
- Cập nhật debug policy, tài liệu và test sang chu kỳ 5 phút.
- Giữ nguyên cơ chế tuần tự 4–5,5 giây, không probe FLV, không gửi Range.

## v0.1.2

- Xác định `auth_key[0]` là Unix expiry.
- Chỉ giữ last-good khi key cũ còn hạn.
- Loại seed/link đã hết hạn.
