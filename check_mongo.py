#!/usr/bin/env python3
"""
Diagnostic tool to test MongoDB Atlas connection and identify exact setup issues.
Usage:
  python3 check_mongo.py
  docker compose exec bot python check_mongo.py
"""
import asyncio
import os
import re
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MONGO_URL = os.environ.get("MONGO_URL", "").strip()
MONGO_NAME = os.environ.get("MONGO_NAME", "megabot").strip()


def mask_url(url: str) -> str:
    """Mask password in URI for safe display."""
    return re.sub(r":([^@]+)@", ":****@", url)


async def test_mongo():
    print("\n🔍 Checking MongoDB Atlas Configuration...")
    print("━" * 55)

    if not MONGO_URL:
        print("❌ MONGO_URL is empty in your .env file!")
        print("\n👉 How to fix:")
        print("   1. Go to MongoDB Atlas (https://cloud.mongodb.com)")
        print("   2. Click 'Connect' on your cluster → Drivers → Python")
        print("   3. Copy your connection string: mongodb+srv://<user>:<password>@cluster...")
        print("   4. Add to .env: MONGO_URL=mongodb+srv://<user>:<password>@cluster...\n")
        return

    masked = mask_url(MONGO_URL)
    print(f"🌐 Target URI: {masked}")
    print(f"📁 Database:   {MONGO_NAME}")
    print("━" * 55)

    # 1. Check if user left localhost:27017
    if "localhost" in MONGO_URL or "127.0.0.1" in MONGO_URL:
        print("⚠️ Warning: Your MONGO_URL is pointing to 'localhost'!")
        print("   In Docker, 'localhost' points inside the container, where no MongoDB is running.")
        print("   If you intended to use MongoDB Atlas, replace 'mongodb://localhost:27017'")
        print("   with your Atlas connection string: mongodb+srv://<user>:<password>@cluster...\n")
        return

    # 2. Check if mongodb+srv prefix is present
    if not MONGO_URL.startswith("mongodb+srv://") and not MONGO_URL.startswith("mongodb://"):
        print("❌ Invalid URI format! It must start with mongodb+srv:// or mongodb://")
        return

    # 3. Check for dnspython
    try:
        import dns.resolver
    except ImportError:
        print("❌ 'dnspython' is not installed! Run: pip install 'dnspython>=2.4.0'")
        return

    # 4. Attempt Motor connection
    try:
        import motor.motor_asyncio
    except ImportError:
        print("❌ 'motor' is not installed! Run: pip install motor")
        return

    print("📡 Connecting to MongoDB Atlas (5s timeout)...")
    start_time = time.time()

    client = motor.motor_asyncio.AsyncIOMotorClient(
        MONGO_URL,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
    )

    try:
        await client.admin.command("ping")
        elapsed = (time.time() - start_time) * 1000
        print(f"✅ MongoDB Atlas connected successfully! (Latency: {elapsed:.1f} ms)")

        # Test database access
        db = client[MONGO_NAME]
        collections = await db.list_collection_names()
        print(f"✅ Database '{MONGO_NAME}' accessible (Collections: {len(collections)})")
        print("━" * 55)
        print("🎉 Your MongoDB Atlas database is 100% ready for MegaBot!\n")

    except Exception as e:
        err_msg = str(e)
        elapsed = (time.time() - start_time) * 1000
        print(f"❌ Connection FAILED after {elapsed:.1f} ms\n")
        print(f"   Raw Error: {err_msg}\n")
        print("━" * 55)
        print("🛠️ How to fix this in MongoDB Atlas:")

        if "timeout" in err_msg.lower() or "serverselectiontimeouterror" in err_msg.lower():
            print("👉 CAUSE 1: IP Access List (Whitelist) is blocking your server!")
            print("   Fix:")
            print("   1. Open MongoDB Atlas (https://cloud.mongodb.com)")
            print("   2. In the left menu, click 'Network Access'")
            print("   3. Click 'Add IP Address'")
            print("   4. Select 'ALLOW ACCESS FROM ANYWHERE' (0.0.0.0/0)")
            print("   5. Click 'Confirm' and wait 1 minute for it to activate.\n")

        elif "authentication" in err_msg.lower() or "bad auth" in err_msg.lower() or "auth" in err_msg.lower():
            print("👉 CAUSE 2: Authentication failed (wrong username or password)")
            print("   Fix:")
            print("   1. Open MongoDB Atlas (https://cloud.mongodb.com)")
            print("   2. In the left menu, click 'Database Access'")
            print("   3. Verify your Database User username exists (it's not your Atlas login email!).")
            print("   4. Click 'Edit' → 'Edit Password' → set a new simple password.")
            print("   5. If your password has special symbols (like @ or : or #), URL-encode them")
            print("      (e.g., '@' becomes '%40', '#' becomes '%23').\n")

        elif "nodename nor servname provided" in err_msg.lower() or "dns" in err_msg.lower():
            print("👉 CAUSE 3: DNS SRV resolution failed.")
            print("   Fix:")
            print("   Your server/container cannot resolve the Atlas cluster hostname.")
            print("   Check your server DNS settings (e.g. 8.8.8.8) or check if the cluster URL is spelled correctly.\n")

        else:
            print("👉 Please double-check your connection string format:")
            print("   mongodb+srv://<username>:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority\n")


if __name__ == "__main__":
    asyncio.run(test_mongo())
