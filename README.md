# SPTV API GitHub v0.1.4

Bản này chạy tự động bằng **GitHub Actions mỗi 5 phút** và lấy URL FLV trực tiếp từ player API SPTV.

## Điểm chính

- Đọc `auth_key[0]` thành Unix expiry và chỉ nhận key còn tối thiểu **300 giây**.
- Không probe URL FLV, không gửi `Range`, không truyền video qua GitHub.
- Gọi player API tuần tự với khoảng nghỉ 4–5,5 giây.
- Ưu tiên trận vừa bắt đầu/đang diễn ra rồi mới tới trận tương lai gần.
- Dừng quét sau tối đa **210 giây** để bảo toàn TTL của key lấy đầu lượt.
- Link cũ chỉ được giữ nếu còn tối thiểu 60 giây sau clock-skew.

## Phân biệt giờ yên và lỗi API

Workflow vẫn **xanh** khi player API trả JSON hợp lệ nhưng không có stream, ví dụ:

```json
{"code": 0, "purl": []}
```

Workflow sẽ **đỏ** và giữ nguyên `sptv.m3u` khi tất cả player API đều:

- timeout hoặc lỗi mạng;
- trả HTTP 4xx/5xx;
- trả JSON lỗi hoặc JSON không có cấu trúc player nhận diện được.

Exit code chính:

- `0`: quét hợp lệ, kể cả giờ yên không có link;
- `2`: không lấy/parse được lịch;
- `3`: toàn bộ player API lỗi hoặc response không hợp lệ.

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

1. Checkout trực tiếp `main` mới nhất và đồng bộ `origin/main`.
2. Chạy unit test.
3. Warm session tại trang chủ SPTV.
4. Tải lịch một lần và lọc cửa sổ `-150/+180` phút.
5. Ưu tiên trận vừa bắt đầu, gọi player API tuần tự.
6. Dừng sớm nếu gặp liên tiếp HTTP 403/429 hoặc hết ngân sách 210 giây.
7. Lọc URL FLV, expiry không hợp lệ và key còn dưới ngưỡng TTL.
8. Ghép link mới với link cũ còn hạn theo stable path.
9. Audit M3U theo cấu trúc `#EXTM3U → #EXTINF → URL`.
10. Chỉ commit khi `sptv.m3u` thực sự thay đổi.
11. Push thẳng `HEAD:main`; không `git pull --rebase` các file key có thời hạn.

Nếu remote thay đổi giữa lúc quét và lúc push, `git push` sẽ bị từ chối và workflow báo đỏ. Lượt cron kế tiếp sẽ checkout branch mới nhất và quét lại, tránh merge hai bộ key có thời điểm khác nhau.

## Lịch tự động

```yaml
schedule:
  - cron: "*/5 * * * *"
```

GitHub lên lịch theo UTC, nhưng biểu thức trên chạy mỗi 5 phút nên không cần đổi múi giờ. GitHub có thể khởi chạy trễ khi hệ thống đông.

`cancel-in-progress: false` để lượt đang chạy không bị lượt kế tiếp hủy giữa chừng. Job đang chờ vẫn checkout trực tiếp `main` mới nhất khi bắt đầu.

## Chạy thủ công

Vào `Actions` → `Update SPTV playlist` → `Run workflow`.

## Quyền workflow

Repository → Settings → Actions → General → Workflow permissions → chọn `Read and write permissions`.

## Link playlist

```text
https://raw.githubusercontent.com/TEN_TAI_KHOAN/TEN_REPOSITORY/main/sptv.m3u
```

## Audit M3U

```bash
python audit_m3u.py sptv.m3u --strict --allow-empty --min-remaining-seconds 30
```

Strict mode từ chối:

- thiếu hoặc lặp `#EXTM3U`;
- URL không có `#EXTINF`;
- `#EXTINF` không có URL;
- hai `#EXTINF` nối tiếp;
- URL FLV thiếu expiry hợp lệ;
- stable path trùng;
- key còn dưới TTL yêu cầu.
