from fastapi import FastAPI, Depends, HTTPException, Header
import uvicorn
from typing import Optional

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Backend Auth Server is Running"}

@app.get("/verify-jwt")
def verify_jwt(authorization: Optional[str] = Header(None)):
    print(f"Received Authorization Header: {authorization}", flush=True)
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    # Ở bước kiểm tra: Chấp nhận mọi Token tạm thời làm mẫu 
    # Bạn sẽ thêm thư viện `python-jose` để phân tích JWT Keycloak ở đây, 
    # Ví dụ: jwt.decode(token, key, algorithms=["RS256"], audience="account")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")
    
    token = authorization.split(" ")[1]
    print(f"Token to verify: {token}", flush=True)
    
    # Giả lập trả về 200 để Nginx proxy-pass tới Minio sau khi auth thành công
    return {"status": "success", "message": "JWT Verified"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
