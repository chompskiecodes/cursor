# pip install elevenlabs
from elevenlabs.client import ElevenLabs
from elevenlabs.conversationalai import ConversationalAI
import json
from datetime import datetime

class VoiceAgentTester:
    def __init__(self, api_key, agent_id):
        self.client = ElevenLabs(api_key=api_key)
        self.agent_id = agent_id
        self.test_results = []
    
    def test_scenario(self, name, messages):
        """Test a conversation scenario"""
        print(f"\n{'='*50}")
        print(f"Testing: {name}")
        print(f"{'='*50}")
        
        conversation = self.client.conversational_ai.create_conversation(
            agent_id=self.agent_id
        )
        
        for message in messages:
            print(f"User: {message}")
            response = conversation.send_text_input(
                text=message,
                session_id=f"test_{datetime.now().timestamp()}"
            )
            print(f"Agent: {response.text}")
            print(f"Tools called: {response.tools_called if hasattr(response, 'tools_called') else 'None'}")
        
        return response