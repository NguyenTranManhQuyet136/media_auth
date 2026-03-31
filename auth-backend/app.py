import logging
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

# ================= XÁC THỰC (VERIFY) =================
@app.route("/verify-jwt", methods=["GET"])
def verify_jwt():
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

    """
    # --- Tầng xác thực (Đã vô hiệu hóa để TEST) ---
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
        # 3. Luôn trả về 200 OK để mọi file video đều được tải mượt mà
        return "", 200

    except Exception as e:
        logger.error(f"❌ Lỗi trong Test Mode: {e}")
        return "", 200 # Ngay cả khi lỗi vẫn cho qua để test
    """

    # 🔓 CHẾ ĐỘ MỞ CỬA: Luôn trả về 200 OK
    return "", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
