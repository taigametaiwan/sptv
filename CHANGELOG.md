# Changelog

## v0.1.4

- Báo lỗi exit code `3` khi toàn bộ player API lỗi/JSON không nhận diện được; giữ nguyên playlist cũ.
- API trả JSON hợp lệ nhưng `purl` rỗng vẫn là giờ yên hợp lệ và workflow xanh.
- Checkout trực tiếp `main`, đồng bộ `origin/main`, bỏ `git pull --rebase` gây conflict key.
- Chỉ commit debug và `lastupdated.txt` khi `sptv.m3u` thực sự thay đổi.
- Thêm ngân sách quét `SPTV_MAX_SCAN_SECONDS=210` và ưu tiên trận vừa bắt đầu.
- Siết strict audit: bắt buộc một `#EXTM3U`, ghép đúng `#EXTINF → URL`, bắt URL/EXTINF mồ côi.
- Sửa logic ghép candidate dưới ngưỡng với link cũ còn hạn.
- Sửa log HTTP để mỗi request attempt chỉ ghi một bản ghi.
- Hỗ trợ metadata trường `m` ở dạng CSV string.
- Từ chối expiry ngoài khoảng năm 2000–2100 ngay tại scanner.

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
