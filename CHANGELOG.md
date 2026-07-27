# Changelog

## v0.1.2

- Sửa kết luận `auth_key[0]`: đây là Unix expiry.
- Thiết kế đúng chu kỳ external `repository_dispatch` mỗi 15 phút.
- Không thêm cron/schedule vào GitHub workflow.
- Lọc key còn tối thiểu 900 giây khi publish.
- Chỉ giữ last-good khi key cũ còn hạn; xóa seed/link đã hết hạn.
- Merge key mới với các path cũ còn hạn để chống mất link do API trả thiếu tạm thời.
- Thêm audit TTL, `lastupdated.txt`, external trigger script.
- Bật `cancel-in-progress: true`, timeout workflow 14 phút.

## v0.1.1

- Xử lý lượt yên giờ không làm workflow đỏ.
- Mở rộng parser player payload.
