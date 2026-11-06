import tempfile
import unittest
from pathlib import Path

from voiceassist.chat_memory import ChatMemory, split_answer
from voiceassist.core import Assistant
from voiceassist.gemini import GeminiHelper


def answer(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class SplitTests(unittest.TestCase):
    def test_marks_are_taken_out_of_the_spoken_answer(self):
        spoken, facts = split_answer("Как хорошо, что внук приехал!\nА надолго он?\nЗАПОМНИ: у Игоря внук Саша учится в Киеве.")
        self.assertEqual(spoken, "Как хорошо, что внук приехал! А надолго он?")
        self.assertEqual(facts, ["у Игоря внук Саша учится в Киеве"])

    def test_answer_without_marks(self):
        self.assertEqual(split_answer("Добрый день!"), ("Добрый день!", []))


class ConversationMemoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.sent = []

    def helper(self, reply):
        helper = GeminiHelper("k", [], "m", post=lambda url, body, key: self.sent.append(body) or answer(reply))
        helper.memory = ChatMemory(self.folder)
        return helper

    def test_next_conversation_knows_the_person_without_extra_requests(self):
        first = self.helper("Давление лучше мерить утром.\nЗАПОМНИ: у человека высокое давление, пьёт таблетки утром")
        self.assertEqual(first.chat(b"", "у меня давление скачет"), "Давление лучше мерить утром.")
        self.assertEqual(len(self.sent), 1)  # one phrase, one request
        first.end_chat()
        later = self.helper("Здравствуйте! Как ваше давление сегодня?")
        later.chat(b"", "привет")
        prompt = self.sent[-1]["systemInstruction"]["parts"][0]["text"]
        self.assertIn("высокое давление", prompt)
        self.assertIn("у меня давление скачет", prompt)  # the end of the last conversation

    def test_memory_stays_small(self):
        memory = ChatMemory(self.folder)
        memory.add(["факт {}".format(number) for number in range(50)])
        self.assertEqual(len(memory.facts()), 30)
        self.assertEqual(memory.facts()[-1], "факт 49")
        memory.add(["Факт 49"])
        self.assertEqual(len(memory.facts()), 30)


class VoiceCommandTests(unittest.TestCase):
    def test_ask_and_forget(self):
        folder = Path(tempfile.mkdtemp())
        assistant = Assistant()
        assistant.config_dir = folder
        ChatMemory(folder).add(["любит рыбалку"])
        self.assertIn("любит рыбалку", assistant.handle("что ты обо мне помнишь").message)
        self.assertIn("да или нет", assistant.handle("забудь всё обо мне").message)
        assistant.handle("да")
        self.assertEqual(ChatMemory(folder).facts(), [])
        self.assertIn("ничего", assistant.handle("что ты обо мне помнишь").message)
