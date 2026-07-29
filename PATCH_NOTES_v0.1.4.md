# SPTV v0.1.4 — Patch notes

## Lỗi được xử lý

1. Job chờ concurrency checkout SHA cũ rồi conflict khi `git pull --rebase`.
2. Toàn bộ player API hỏng nhưng scanner vẫn có thể trả exit code 0.
3. Strict audit cho qua URL mồ côi hoặc `#EXTINF` mồ côi.
4. Candidate mới dưới ngưỡng có thể bị bỏ dù ghép với link cũ đủ ngưỡng.
5. Scanner có thể quét quá lâu và làm giảm TTL key lấy đầu lượt.
6. Một HTTP attempt có thể bị ghi trùng trong debug.
7. Metadata `m` dạng CSV string không được parse.
8. Expiry vô lý chưa bị loại ngay trong scanner.

## Cách áp dụng gói patch

```bash
unzip SPTV_PATCH_v0.1.3_to_v0.1.4.zip
cd SPTV_PATCH_v0.1.3_to_v0.1.4
chmod +x APPLY_PATCH.sh
./APPLY_PATCH.sh /duong/dan/toi/repository-sptv
```

Script tạo backup trước khi ghi đè và tự rollback nếu compile/unit test thất bại.
