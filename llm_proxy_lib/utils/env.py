import os


def bool_env_value(env_name: str) -> bool:
    """
    Return a boolean derived from an environment variable.

    Reads the environment variable named by `env_name` and interprets common
    truthy strings case-insensitively as True: "true", "1", "t", "y", "yes", "tak".
    If the variable is unset, the default value "false" is used and the function
    returns False. Any other value yields False.

    Args:
        env_name: The name of the environment variable to read.

    Returns:
        bool: True if the variable value is a recognized truthy string; otherwise False.

    Examples:
        >>> import os
        >>> os.environ["FEATURE_ENABLED"] = "Yes"
        >>> bool_env_value("FEATURE_ENABLED")
        True
        >>> os.environ.pop("FEATURE_ENABLED", None)
        >>> bool_env_value("FEATURE_ENABLED")
        False
    """
    env_value = os.getenv(env_name, "false").lower()
    if env_value in ["true", "1", "t", "y", "yes", "tak"]:
        env_value = True
    else:
        env_value = False
    return env_value
