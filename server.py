"""
Start the Gmail Assistant local server.
Run this before using the Chrome extension.

    python server.py
"""

import os
import sys


def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        # Try loading .env manually before giving up
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set.")
        print("  1. Copy .env.example to .env")
        print("  2. Add your key:  ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    if not os.path.exists("credentials/credentials.json"):
        print("Error: credentials/credentials.json not found.")
        print("  Follow SETUP.md Step 2 to create Gmail API credentials.")
        sys.exit(1)

    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    print("=" * 50)
    print("  Gmail Assistant — Local Server")
    print("=" * 50)
    print("\n  Server:    http://localhost:8000")
    print("  Open Gmail, then click the extension icon.\n")

    # In Docker (SERVER_HOST=0.0.0.0) the container must bind on all interfaces
    # so the port-mapping reaches the process. Locally we stay on 127.0.0.1.
    host = os.environ.get("SERVER_HOST", "127.0.0.1")

    uvicorn.run(
        "src.server:app",
        host=host,
        port=8000,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
