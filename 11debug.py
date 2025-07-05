# test_agent_simple.py
import os
from elevenlabs import ElevenLabs
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
AGENT_ID = "agent_01jy9b76f9e5f8et1xy1df59yt"

client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

print(f"Testing agent: {AGENT_ID}")

try:
    # The correct way to test conversation AI
    conversation = client.conversational_ai.begin_conversation(agent_id=AGENT_ID)
    print("✓ Successfully connected to agent!")
    print(f"Conversation ID: {conversation.conversation_id}")
    
    # End the test conversation
    conversation.end_conversation()
    print("✓ Test completed successfully")
    
except Exception as e:
    print(f"Error: {e}")
    print("\nPossible issues:")
    print("1. Check if agent ID is correct")
    print("2. Ensure your API key has Conversational AI access")
    print("3. Verify the agent is published/active")