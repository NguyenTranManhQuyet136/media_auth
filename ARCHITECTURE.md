# 📦 Media Auth Gateway — Tài liệu Kiến trúc Chi tiết

> **Mục đích:** Tài liệu này mô tả toàn bộ kiến trúc, luồng xác thực, và các vấn đề kỹ thuật của hệ thống Media Authentication Gateway — cầu nối bảo mật giữa Open edX và MinIO.

---

## 📌 Tóm tắt Dự án

Hệ thống này đóng vai trò là một **Cổng Bảo mật Phương tiện (Secure Media Gateway)**, có nhiệm vụ:
- **Bảo vệ** các file video/media riêng tư trong MinIO khỏi truy cập trái phép.
- **Xác thực** mọi yêu cầu tải media bằng JWT do Open edX phát hành (thuật toán RS512).
- **Chuyển tiếp** yêu cầu hợp lệ tới MinIO để phát video cho người dùng.

---

## 🏗️ Kiến trúc Tổng thể

```
[Trình duyệt / Học viên]
         │
         │ HTTP GET http://minio.local:8081/openedx/demo/0/master.m3u8
         │          (Tùy chọn: ?token=JWT_TOKEN)
         ▼
┌─────────────────────┐
│   Nginx (Port 8081) │  ← Cổng chính, kiểm soát luồng
│  mino.local.conf    │
└──────┬──────────────┘
       │
       │ auth_request /auth  (Sub-request nội bộ, KHÔNG thấy ở trình duyệt)
       ▼
┌──────────────────────────┐
│  Auth-Backend (Port 8080)│  ← Flask App, là "Thẩm phán"
│  /verify-jwt             │
│  - Kiểm tra JWT RS512    │
│  - Log toàn bộ Headers   │
│  - Trả về 200 / 401      │
└──────────────────────────┘
       │
       │ 200 OK → Nginx cho phép
       │ 401    → Nginx từ chối, trả lỗi cho trình duyệt
       ▼
┌───────────────────────────┐
│   MinIO (Port 9000 nội bộ)│  ← Kho lưu trữ thực sự
│   Bucket: openedx         │
│   File: *.m3u8, *.ts      │
└───────────────────────────┘
```

---

## 🐳 Cấu hình Docker Compose

| Service          | Container Name        | Port Nội bộ | Port Expose   | Vai trò                    |
|------------------|-----------------------|-------------|----------------|----------------------------|
| `nginx`          | `media_nginx`         | 80          | `0.0.0.0:8081` | Cổng chính, Reverse Proxy  |
| `auth-backend`   | `media_auth_backend`  | 8080        | Không expose   | Xác thực JWT, Ghi Log      |
| `minio`          | `media_minio`         | 9000, 9001  | `9004`, `9003` | Lưu trữ Video/Media        |

**Network chung:** `media_net` (Bridge) — Tất cả 3 service có thể giao tiếp với nhau qua tên service.

---

## 🔐 Luồng Xác thực Chi tiết

### Bước 1: Trình duyệt gửi yêu cầu

Trình duyệt mở link video theo một trong hai cách:

```
# Cách 1: Token trên URL (dễ test)
GET http://minio.local:8081/openedx/demo/0/master.m3u8?token=eyJhbGci...

# Cách 2: Token trong Header (bảo mật hơn)
GET http://minio.local:8081/openedx/demo/0/master.m3u8
Authorization: Bearer eyJhbGci...
```

### Bước 2: Nginx nhận và phân tích

Nginx nhận yêu cầu và chạy logic trong `mino.local.conf`:

```nginx
# Ưu tiên Authorization header, fallback sang ?token= trên URL
set $effective_token $http_authorization;
if ($effective_token = "") {
    set $effective_token "Bearer $arg_token";
}
```

### Bước 3: Nginx gửi Sub-request ngầm tới Auth-Backend

```nginx
auth_request /auth;   # Nginx tự động gửi sub-request này

location = /auth {
    internal;  # Chỉ dùng nội bộ, không thể gọi từ bên ngoài
    set $auth_backend "http://auth-backend:8080";
    proxy_pass $auth_backend/verify-jwt?$query_string;
    
    # QUAN TRỌNG: Chuyển tiếp các thông tin bảo mật cho Backend
    proxy_set_header Authorization $effective_token;
    proxy_set_header Cookie         $http_cookie;
    proxy_set_header Referer        $http_referer;
    proxy_set_header User-Agent     $http_user_agent;
    proxy_set_header X-Original-URI $request_uri;
}
```

> **Tại sao dùng biến `$auth_backend`?**  
> Nếu dùng `proxy_pass http://auth-backend:8080` trực tiếp, Nginx sẽ báo lỗi `host not found` khi khởi động trước Auth-Backend. Dùng biến giúp Nginx chỉ tra DNS khi có request thực tế.

### Bước 4: Auth-Backend xác thực JWT (RS512)

Flask app tại `/verify-jwt` thực hiện:

1. **Log toàn bộ thông tin** nhận được (để debug).
2. **Trích xuất Token** theo thứ tự ưu tiên:
   - `Authorization: Bearer xxx` header
   - `?token=xxx` trên URL
   - `token=xxx` trong `X-Original-URI`
3. **Xác thực JWT RS512** bằng Public Key nhúng sẵn.
4. **Trả về kết quả**:
   - `200 OK` → Nginx cho tải file từ MinIO.
   - `401 Unauthorized` → Nginx trả lỗi cho trình duyệt.

### Bước 5: Nginx chuyển tiếp hoặc từ chối

```
200 từ Backend → proxy_pass http://minio_backend → File video được trả về
401 từ Backend → error_page 401 @error401 → JSON lỗi được trả về
```

---

## 🗝️ Cấu hình JWT và Public Key

Open edX phát hành JWT theo thuật toán **RS512** (RSA với SHA-512). Backend sử dụng **Public Key** nhúng cứng (hardcoded JWKS) để xác minh chữ ký:

```python
def get_jwks():
    return {
        "keys": [{
            "kid": "openedx",
            "kty": "RSA",
            "e": "AQAB",
            "n": "xI12xtIFheD7..."  # Public key của Open edX instance
        }]
    }
```

> ⚠️ **Lưu ý Production:** Public Key này cần được lấy từ endpoint JWKS động của Open edX:  
> `http://local.openedx.io/api/user/v1/public_jwks/`

---

## 🕵️ Hệ thống Ghi Log Debug

Auth-Backend hiện đang ghi lại **TOÀN BỘ** thông tin của mỗi request:

```python
logger.info("--- 📥 NHẬN YÊU CẦU MỚI ---")
logger.info(f"🌐 IP: {request.remote_addr}")
logger.info(f"📍 URI: {request.headers.get('X-Original-URI', 'N/A')}")
logger.info(f"🍪 [COOKIES]: {dict(request.cookies)}")
logger.info("📑 [HEADERS]:")
for key, value in request.headers.items():
    logger.info(f"   -> {key}: {value}")
```

**Cách xem log theo thời gian thực:**
```bash
docker compose logs -f auth-backend
```

---

## 🌐 Vấn đề Cross-Domain và Cookie

### Vấn đề cốt lõi

```
Open edX Studio: http://studio.local.openedx.io    (Domain A)
Media Gateway:   http://minio.local:8081            (Domain B — khác nhau!)
```

Trình duyệt **KHÔNG BAO GIỜ** tự động gửi Cookie của Domain A sang Domain B vì quy tắc bảo mật SameSite. Đây là lý do `🍪 [COOKIES]: {}` luôn trống.

### Biểu hiện trong Log

```
🍪 [COOKIES]: {}                      ← Trống! Không có sessionid
-> Authorization: Bearer              ← Chỉ có "Bearer" nhưng thiếu token
-> Referer: http://studio.local.openedx.io/
```

### Giải pháp đang được nghiên cứu

#### Phương án 1: URL Token (Đang dùng để test)
```
http://minio.local:8081/openedx/demo/0/master.m3u8?token=JWT_TOKEN
```
- ✅ Đơn giản, test ngay được
- ❌ Token lộ trên URL, không phù hợp production

#### Phương án 2: Same-Domain Proxy (Khuyên dùng)
Cấu hình Nginx để Media Gateway nhận yêu cầu trên cùng domain với Studio:
```
http://studio.local.openedx.io:8081/openedx/demo/0/master.m3u8
```
- ✅ Trình duyệt TỰ ĐỘNG gửi `sessionid` của Open edX
- ✅ Có thể xác thực qua LMS API
- ❌ Cần cập nhật `server_name` trong Nginx

#### Phương án 3: JWT Handshake + Cookie (Production)
1. Frontend lấy JWT từ Open edX.
2. Gọi endpoint `/handshake?token=JWT` một lần.
3. Backend xác thực JWT, phát hành Cookie `media_session` riêng.
4. Mọi request sau dùng Cookie này — không cần gửi JWT mỗi lần.

---

## 📁 Cấu trúc Dự án

```
d:\edxdoc\media_auth\
├── docker-compose.yml          # Định nghĩa 3 service
├── nginx.conf                  # Cấu hình Nginx chính (worker, log format)
├── ARCHITECTURE.md             # File tài liệu này
│
├── conf.d\
│   └── mino.local.conf         # Server block cho minio.local và console.minio.local
│
├── auth-backend\
│   ├── Dockerfile              # Build image Flask
│   ├── requirements.txt        # python-jose, flask, gunicorn
│   └── app.py                  # Logic xác thực JWT RS512 + Logging
│
└── logs\
    ├── access.log              # Log truy cập Nginx
    └── error.log               # Log lỗi Nginx
```

---

## 🚧 Trạng thái Hiện tại (31/03/2026)

| Thành phần       | Trạng thái          | Ghi chú                                          |
|------------------|---------------------|--------------------------------------------------|
| Nginx            | ✅ Đang chạy         | Cổng 8081, CORS đã bật cho `*.local`             |
| Auth-Backend     | ✅ Đang chạy         | Bảo mật RS512 **ĐÃ BẬT**, log toàn bộ headers   |
| MinIO            | ✅ Đang chạy         | Chia sẻ volume với instance MinIO cũ             |
| Nhận Cookie      | ❌ Chưa hoạt động    | Do Cross-Domain — Cookie luôn trống              |
| Nhận JWT Token   | ✅ Hoạt động         | Qua `?token=` hoặc `Authorization: Bearer`      |

---

## 🔮 Bước tiếp theo

1. **[Ưu tiên cao]** Chuyển `server_name` sang `studio.local.openedx.io:8081` để hứng được `sessionid`.
2. **[Ưu tiên cao]** Thay Public Key hardcoded bằng việc gọi động JWKS endpoint của Open edX.
3. **[Trung bình]** Triển khai cơ chế "Handshake" (JWT đổi lấy Cookie) để bảo mật tốt hơn.
4. **[Thấp]** Tắt log debug khi đưa lên production.
5. **[Tương lai]** Chuyển sang HTTPS với Let's Encrypt hoặc self-signed cert.

---

## 🔗 Tài nguyên Liên quan

- **GitHub:** `https://github.com/NguyenTranManhQuyet136/media_auth`
- **MinIO Console:** `http://console.minio.local:8081` (User: `admin`)
- **Xem Log Backend:** `docker compose logs -f auth-backend`
- **Kiểm tra Nginx:** `docker compose logs nginx --tail 20`
- **Open edX JWKS:** `http://local.openedx.io/api/user/v1/public_jwks/`
