from typing import Dict, Any, Optional

ERROR_NO_REQUIRED_PARAMS = "No required parameters!"


def error_as_dict(error: str, error_msg: Optional[str] = None) -> Dict[str, Any]:
    if error_msg is None:
        return {"error": error}

    return {"error": error, "message": error_msg}
