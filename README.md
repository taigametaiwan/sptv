# SPTV API GitHub v0.1.2

Bản này mô phỏng đúng cơ chế đã xác định từ playlist tham chiếu:

- `auth_key[0]` là **Unix expiry**, không phải thời điểm cấp key.
- Key quan sát được sống khoảng 25 phút.
- Workflow được **cron bên ngoài gọi mỗi 15 phút** để key mới chồng lấn key cũ.
- Trong `.github/workflows/update-sptv.yml` không có `schedule` hay cron nội bộ.
- GitHub không probe FLV và không truyền video; người xem tải thẳng CDN SPTV.

## Cấu trúc bắt buộc trên GitHub

```text
.github/workflows/update-sptv.yml
external_trigger/trigger_sptv.sh
tests/test_core.py
sptv_api.py
audit_m3u.py
requirements.txt
sptv.m3u
lastupdated.txt
```

Hãy tải toàn bộ nội dung thư mục này lên gốc repository, không để thừa một tầng thư mục.

## Cơ chế một lượt chạy

1. Warm session tại trang chủ SPTV.
2. Tải lịch một lần.
3. Lọc trận trong cửa sổ `-150/+180` phút.
4. Gọi player API tuần tự, nghỉ ngẫu nhiên 4–5,5 giây.
5. Không gọi thử URL FLV, không gửi `Range`, không thử nhiều profile header.
6. Đọc `auth_key[0]` thành thời điểm hết hạn.
7. Chỉ nhận key còn tối thiểu 900 giây tại lúc xuất playlist.
8. Link cũ chỉ được giữ khi vẫn còn hạn; link đã hết hạn bị xóa.
9. Workflow commit `sptv.m3u`, `debug/sptv_debug.json`, `lastupdated.txt`.

## Vì sao phải gọi mỗi 15 phút?

Playlist tham chiếu được làm mới mỗi 15 phút trong khi key còn sống khoảng 25 phút. Vì vậy thường có 6–10 phút chồng lấn giữa thế hệ key cũ và mới. URL Raw/GitHub Pages đứng yên, nhưng nội dung `sptv.m3u` thay đổi liên tục.

## Chạy thủ công

Vào `Actions` → `Update SPTV playlist` → `Run workflow`.

## Kích hoạt từ cron bên ngoài mỗi 15 phút

Workflow nhận các event:

```text
refresh-sptv
trigger-sptv-from-cronjob
trigger-ththethao-from-cronjob
```

Ví dụ trên VPS hoặc máy cron riêng:

```bash
export GITHUB_OWNER="TEN_TAI_KHOAN"
export GITHUB_REPO="TEN_REPOSITORY"
export GITHUB_TOKEN="TOKEN_CO_QUYEN_ACTIONS_CONTENTS"

bash external_trigger/trigger_sptv.sh
```

Crontab bên ngoài:

```cron
*/15 * * * * GITHUB_OWNER='TEN_TAI_KHOAN' GITHUB_REPO='TEN_REPOSITORY' GITHUB_TOKEN='TOKEN' /bin/bash /duong-dan/external_trigger/trigger_sptv.sh >> /tmp/sptv_dispatch.log 2>&1
```

Không chép dòng cron này vào workflow YAML. Nếu dùng cron-job.org hoặc dịch vụ tương tự, cấu hình POST tới GitHub repository dispatch với JSON:

```json
{"event_type":"refresh-sptv"}
```

## Quyền workflow

Repository → Settings → Actions → General → Workflow permissions → chọn `Read and write permissions`.

## Link playlist

```text
https://raw.githubusercontent.com/TEN_TAI_KHOAN/TEN_REPOSITORY/main/sptv.m3u
```

Repository public sẽ thuận tiện hơn cho IPTV/Gấu Player đọc Raw URL.

## Bảo vệ chống lỗi

- Hai lần liên tiếp gặp HTTP 403/429 thì dừng sớm.
- `cancel-in-progress: true`: lượt dispatch mới hủy lượt cũ nếu bị kéo dài quá 15 phút.
- Candidate rỗng chỉ giữ key cũ nếu key đó chưa hết hạn.
- Không dùng 41 link seed cũ vì chúng đã hết hạn và không có giá trị dự phòng.
- Audit từ chối URL thiếu expiry, trùng path, malformed hoặc đã quá hạn.
