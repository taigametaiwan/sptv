# SPTV API GitHub v0.1.3

Bản này chạy tự động bằng **GitHub Actions mỗi 5 phút**:

- `auth_key[0]` được đọc là Unix expiry.
- Lượt API thực tế ngày 27/07/2026 trả key chỉ còn khoảng 10 phút.
- Ngưỡng publish hạ từ 900 xuống **300 giây** để không loại nhầm luồng hợp lệ.
- Workflow có `schedule: */5 * * * *`, đồng thời vẫn hỗ trợ chạy thủ công và `repository_dispatch`.
- GitHub không probe FLV và không truyền video; người xem tải thẳng CDN SPTV.

## Tệp cần đặt ở gốc repository

```text
.github/workflows/update-sptv.yml
tests/test_core.py
sptv_api.py
audit_m3u.py
requirements.txt
sptv.m3u
lastupdated.txt
```

Tải toàn bộ nội dung thư mục này lên gốc repository, không để thừa một tầng thư mục.

## Cơ chế một lượt chạy

1. Warm session tại trang chủ SPTV.
2. Tải lịch một lần.
3. Lọc trận trong cửa sổ `-150/+180` phút.
4. Gọi player API tuần tự, nghỉ ngẫu nhiên 4–5,5 giây.
5. Không gọi thử URL FLV, không gửi `Range`, không thử nhiều profile header.
6. Đọc `auth_key[0]` thành thời điểm hết hạn.
7. Chỉ nhận key còn tối thiểu 300 giây sau khi trừ 30 giây clock-skew.
8. Link cũ chỉ được giữ khi vẫn còn ít nhất 60 giây; link hết hạn bị xóa.
9. Commit `sptv.m3u`, `debug/sptv_debug.json`, `lastupdated.txt`.

## Lịch tự động

Workflow chứa:

```yaml
schedule:
  - cron: "*/5 * * * *"
```

GitHub lên lịch theo UTC, nhưng biểu thức này chạy mỗi 5 phút nên không cần đổi múi giờ. GitHub có thể khởi chạy trễ vài phút khi hệ thống đông; đây là giới hạn của Actions chứ không phải lỗi code.

`cancel-in-progress: false` để lượt đang lấy key không bị lượt kế tiếp hủy giữa chừng. Với cùng một concurrency group, GitHub chỉ cho một lượt chạy và tối đa một lượt chờ.

## Chạy thủ công

Vào `Actions` → `Update SPTV playlist` → `Run workflow`.

## Quyền workflow

Repository → Settings → Actions → General → Workflow permissions → chọn `Read and write permissions`.

## Link playlist

```text
https://raw.githubusercontent.com/TEN_TAI_KHOAN/TEN_REPOSITORY/main/sptv.m3u
```

## Bảo vệ chống lỗi

- Hai lần liên tiếp gặp HTTP 403/429 thì dừng sớm.
- Candidate rỗng chỉ giữ key cũ nếu key đó chưa hết hạn.
- Không dùng link seed cũ đã hết hạn.
- Audit từ chối URL thiếu expiry, trùng path, malformed hoặc chỉ còn dưới 30 giây.
- `workflow_dispatch` và `repository_dispatch` vẫn được giữ để kiểm thử hoặc kích hoạt bổ sung.
