#!/usr/bin/env python3
# Quick diagnostic tool to test OpenRouter AI connection & agent setup
import asyncio
import time
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL
from megabot.ai.client import call_openrouter_json
from megabot.ai.planner import plan_actions


async def test_connection():
    print("\n🔍 Checking MegaBot AI Agent Configuration...")
    print("━" * 50)

    # 1. Check API Key presence
    if not OPENROUTER_API_KEY:
        print("❌ OPENROUTER_API_KEY is NOT set in your .env file!")
        print("\n👉 How to fix:")
        print("   1. Open .env")
        print("   2. Add: OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxx")
        print("   3. Run this script again: python3 check_ai.py\n")
        return False

    masked_key = OPENROUTER_API_KEY[:8] + "..." + OPENROUTER_API_KEY[-4:]
    print(f"✅ API Key detected: {masked_key}")
    print(f"🌐 Base URL:        {OPENROUTER_BASE_URL}")
    print(f"🧠 Model:           {OPENROUTER_MODEL}")
    print("━" * 50)
    print("📡 Testing live connection to OpenRouter...")

    # 2. Test ping
    start_time = time.time()
    try:
        test_response = await call_openrouter_json(
            system_prompt="You are a health check assistant. Respond in JSON format: {'status': 'operational', 'message': 'AI Agent online'}",
            user_prompt="Ping",
        )
        latency = round((time.time() - start_time) * 1000, 1)

        if test_response and test_response.get("status") == "operational":
            print(f"✅ Connection successful! (Latency: {latency} ms)")
        else:
            print(f"⚠️ Connected, but received unexpected payload: {test_response}")
            return False

    except Exception as e:
        print(f"❌ Connection failed with error: {e}")
        return False

    # 3. Test Agent File Planning Logic
    print("🧠 Testing Agent decision-making on mock file metadata...")
    mock_metadata = {
        "total_files": 5,
        "total_size": "12.4 MB",
        "category_breakdown": {"image": 5},
        "files": [
            {"name": f"page_{i}.jpg", "extension": ".jpg", "category": "image", "size_human": "2.4 MB"}
            for i in range(1, 6)
        ]
    }
    user_prompt = "merge all images into Chapter1.pdf"

    plan = await plan_actions(mock_metadata, user_prompt)
    if plan and "actions" in plan:
        print(f"✅ Agent Planning operational!")
        print(f"   Summary: {plan.get('summary')}")
        print(f"   Actions: {[a.get('action') for a in plan.get('actions', [])]}")
        print("━" * 50)
        print("🎉 All checks passed! Your bot is fully connected as an AI Agent.\n")
        return True
    else:
        print(f"⚠️ Planning test returned invalid plan: {plan}")
        return False


if __name__ == "__main__":
    asyncio.run(test_connection())
