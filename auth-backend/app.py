import logging
import re
import requests
from flask import Flask, request
from jose import jwt


EXPECTED_AUDIENCE = "openedx" 


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
app = Flask(__name__)


def get_jwks():
    return {
        "keys": [
            {
                "kid": "openedx",
                "kty": "RSA",
                "e": "AQAB",
                "n": "xI12xtIFheD7kgTy4gXyoAsdf9wlCppsAeJYsQfann7b8BvxDEmEk2V1GxDWfatSgkKpL4Lh1fhhiNR437QFGkCh7zvMobWkw7Tpazh_rCn4SwYb_7rQODHu4VVfSgATU-Qfs-O7QERa8pCLVxujFohWgYfYnbJZDrF6IQxR43C8onWmhVeK17aWoPyKN2TAEYZKm_a7kZX3iMAGqT7mOPCIpSQO6d41DyzQt8pgMBiX4uPzO0oDjwfTxqo_WCTZI9fosRRmhTFK8-PtXBYhsTej62gVY1sQNdWs9roO6UBTp8Liriu0SZkZt-wkbe9Y7uuopgTkq2hSel1g5Ip0qQ"
            }
        ]
    }

def get_public_key(token):
    try:
        headers = jwt.get_unverified_header(token)
        kid = headers.get("kid")
        jwks = get_jwks()

        # Tìm chìa khóa khớp với thẻ 'kid', nếu không có thì lấy chìa khóa mặc định
        if not kid and jwks.get("keys"):
            return jwks["keys"][0]
            
        for key in jwks["keys"]:
            if key["kid"] == kid: return key
            
        return jwks["keys"][0]
    except Exception as e:
        logger.error(f"❌ Lỗi đọc khóa: {e}")
        return None

@app.route("/verify-jwt", methods=["GET"])
def verify_jwt():
    # 🕵️‍♂️ [DEBUG] HỨNG TRỌN BỘ THÔNG TIN TỪ TRÌNH DUYỆT / OPEN EDX
    logger.info("--- 📥 NHẬN YÊU CẦU MỚI ---")
    logger.info(f"🌐 IP: {request.remote_addr}")
    logger.info(f"📍 URI: {request.headers.get('X-Original-URI', 'N/A')}")
    logger.info(f"🍪 [COOKIES]: {dict(request.cookies)}")
    
    # In tất cả các Header liên quan để bạn soi
    logger.info("📑 [HEADERS]:")
    for key, value in request.headers.items():
        logger.info(f"   -> {key}: {value}")

    # Lấy thông tin từ Nginx (URI gốc, Authorization)
    original_uri = request.headers.get("X-Original-URI", "")
    auth_header = request.headers.get("Authorization", "")
    
    token = None

    # --- Ưu tiên mã Token trong Header ---
    if auth_header and len(auth_header.split()) >= 2:
        token = auth_header.split()[-1] 

    # --- Fallback: Lấy mã Token trên URL (?token=...) ---
    if not token:
        token = request.args.get("token")

    # --- Dự phòng: soi từ X-Original-URI nếu Nginx làm rơi tham số ---
    if not token and original_uri and "token=" in original_uri:
        token = original_uri.split("token=")[-1].split("&")[0]

    # --- Tầng xác thực RS512 ---
    if not token: 
        logger.warning(f"🚫 Từ chối truy cập (Thiếu Token): {original_uri}")
        return "", 401

    try:
        # Xác thực Token RS512 của Open edX
        key = get_public_key(token)
        if not key: return "", 401

        payload = jwt.decode(
            token, key, algorithms=["RS512"],
            audience=EXPECTED_AUDIENCE, 
            options={"verify_aud": False} 
        )

        logger.info(f"✅ Hợp lệ cho User: {payload.get('preferred_username', 'User')}")
        return "", 200

    except Exception as e:
        logger.warning(f"❌ Xác thực rớt (Token Sai/Hết hạn): {e}")
        return "", 401

@app.route('/rewrite-playlist')
def rewrite_playlist():
    """
    Endpoint chuyên dụng để 'độ' file .m3u8:
    Tự động chèn ?token=... vào các file .ts bên trong để trình duyệt tải được streaming.
    """
    token = request.args.get("token")
    # Lấy đường dẫn file gốc từ Header X-Original-URI mà Nginx gửi sang
    original_uri = request.headers.get("X-Original-URI", "")
    
    # 1. Soát vé trước khi làm việc
    status_code = verify_jwt()[1]
    if status_code != 200:
        logger.warning(f"🚫 Từ chối Rewrite (Token sai): {original_uri}")
        return "Unauthorized", 401

    try:
        # 2. Gắp file m3u8 gốc từ MinIO cổng 9000 (Giao tiếp nội bộ giữa các container)
        # Bỏ đi phần '/auth' nếu có trong URI
        clean_path = original_uri.split('?')[0]
        minio_url = f"http://minio:9000{clean_path}"
        
        resp = requests.get(minio_url)
        if resp.status_code != 200:
            return f"Không tìm thấy file trên MinIO: {clean_path}", 404
        
        m3u8_content = resp.text

        # 3. 'Lươn lẹo' thông minh: 
        # Tìm các file (.ts hoặc .m3u8) mà CHƯA CÓ dấu hỏi chấm (?) đằng sau để gắn Token.
        # Điều này giúp hỗ trợ cả Master Playlist gọi Playlist con.
        rewritten_content = re.sub(r'(\.(ts|m3u8))(?!\?)', rf'\1?token={token}', m3u8_content)

        # Log một đoạn nội dung để kiểm tra
        sample = rewritten_content[:200].replace('\n', ' ')
        logger.info(f"✅ Đã 'độ' xong {clean_path}. Nội dung xem trước: {sample}...")
        
        # 4. Trả về cho trình duyệt với Header chuẩn HLS
        return rewritten_content, 200, {
            'Content-Type': 'application/vnd.apple.mpegurl',
            'Access-Control-Allow-Origin': '*'
        }
        
    except Exception as e:
        logger.error(f"💥 Lỗi khi xử lý Rewrite: {str(e)}")
        return "Internal Server Error", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
