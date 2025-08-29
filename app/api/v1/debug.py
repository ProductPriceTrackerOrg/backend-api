from fastapi import APIRouter, Depends, Request
from jose import jwt

from app.api.deps import security
from app.config import settings

router = APIRouter()

@router.post("/debug-token", summary="Debug JWT token")
async def debug_jwt_token(request: Request):
    """
    A diagnostic endpoint to analyze and debug JWT tokens.
    Provide the token in the Authorization header as "Bearer <token>".
    """
    try:
        # Get the authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return {"error": "Invalid Authorization header format. Use 'Bearer <token>'"}
            
        # Extract the token
        token = auth_header.split(" ")[1]
        
        # First, analyze the token without verification
        unverified_payload = jwt.decode(
            token,
            options={"verify_signature": False}
        )
        
        # Now try to verify with our settings
        try:
            verified_payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_signature": True, "verify_aud": False, "verify_exp": True}
            )
            verification_status = "SUCCESS"
        except Exception as e:
            verified_payload = None
            verification_status = f"FAILED: {str(e)}"
        
        return {
            "token_structure": {
                "header": token.split(".")[0],
                "payload": unverified_payload,
                "signature_present": len(token.split(".")) > 2
            },
            "verification": {
                "status": verification_status,
                "verified_payload": verified_payload
            },
            "debug_info": {
                "sub_present": "sub" in unverified_payload,
                "exp_present": "exp" in unverified_payload,
                "aud_present": "aud" in unverified_payload,
                "algorithm": jwt.get_unverified_header(token).get("alg"),
            }
        }
    except Exception as e:
        return {"error": f"Failed to parse token: {str(e)}"}
