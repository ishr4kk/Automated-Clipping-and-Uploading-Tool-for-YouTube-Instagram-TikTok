

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import yt_uploader.oauth as oauth
    import yt_uploader.logger as logger_mod
else:
    from . import oauth
    from . import logger as logger_mod

if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logger_mod.configure()
    oauth.run_oauth_flow()
    logger_mod.log(f"Authorization complete. Token: {oauth.token_summary()}")
