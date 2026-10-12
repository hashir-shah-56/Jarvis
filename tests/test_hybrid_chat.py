import unittest
from ai.hybrid_chat import HybridChat
from ai.models import AssistantText, ProviderError
class Fake:
    def __init__(self, value):self.value=value;self.calls=0
    def chat(self, prompt):self.calls+=1;return self.value
class HybridTests(unittest.TestCase):
    def test_local_only(self):
        local=Fake(AssistantText('local'));cloud=Fake(AssistantText('cloud'))
        self.assertEqual(HybridChat(local,cloud).chat('hello','local'),(AssistantText('local'),'local',False));self.assertEqual(cloud.calls,0)
    def test_cloud_only(self):
        local=Fake(AssistantText('local'));cloud=Fake(AssistantText('cloud'))
        self.assertEqual(HybridChat(local,cloud).chat('hello','gemini'),(AssistantText('cloud'),'gemini',False));self.assertEqual(local.calls,0)
    def test_fallback_429(self):
        local=Fake(AssistantText('local'));cloud=Fake(ProviderError('AI_RATE_LIMITED'))
        self.assertEqual(HybridChat(local,cloud).chat('hello','auto'),(AssistantText('local'),'local',True))
    def test_no_fallback_on_auth(self):
        local=Fake(AssistantText('local'));cloud=Fake(ProviderError('AI_AUTH_FAILED'))
        self.assertEqual(HybridChat(local,cloud).chat('hello','auto'),(ProviderError('AI_AUTH_FAILED'),'gemini',False));self.assertEqual(local.calls,0)
    def test_invalid_input_never_contacts_provider(self):
        local=Fake(AssistantText('local'));cloud=Fake(AssistantText('cloud'))
        self.assertEqual(HybridChat(local,cloud).chat('','auto')[0],ProviderError('AI_INVALID_INPUT'));self.assertEqual(local.calls+cloud.calls,0)
if __name__=='__main__':unittest.main()
