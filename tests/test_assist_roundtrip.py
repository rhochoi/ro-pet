import json
import tempfile
import unittest
from pathlib import Path

from ro import engines


class AssistRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = Path(self.tmp.name)
        self.dl = r / "Downloads"
        self.docs = r / "Documents" / "회사 기밀"
        self.dl.mkdir()
        self.docs.mkdir(parents=True)
        self.files = [self.dl / "김철수_연봉계약서.pdf", self.dl / "IMG_0001.HEIC"]
        for f in self.files:
            f.write_text("본문 비밀 내용")
        self.text, self.map = engines.assist_payload(self.files, [self.dl, self.docs])

    def tearDown(self):
        self.tmp.cleanup()

    def test_payload_has_only_ids_and_meta(self):
        for leak in ("김철수", "연봉", "IMG_0001", "회사 기밀", "Downloads", self.tmp.name, "본문"):
            self.assertNotIn(leak, self.text)
        body = json.loads(self.text.rsplit("\n\n", 1)[1])
        self.assertEqual([f["id"] for f in body["files"]], ["F1", "F2"])
        self.assertEqual(body["files"][0]["ext"], ".pdf")
        self.assertEqual(body["files"][0]["in"], "T1")
        self.assertEqual(self.map["T2"], str(self.docs))

    def test_valid_reply_maps_back_to_real_paths(self):
        reply = '```json\n{"moves": [{"file": "F1", "to": "T2"}, {"file": "F2", "to": "N1"}],' \
                ' "new_folders": [{"id": "N1", "parent": "T1", "name": "사진"}]}\n```'
        out = engines.assist_reply(reply, self.map)
        self.assertEqual(out["moves"][0], (str(self.files[0]), str(self.docs)))
        self.assertEqual(out["moves"][1], (str(self.files[1]), ("new", "N1")))
        self.assertEqual(out["new_folders"]["N1"], (str(self.dl), "사진"))

    def test_injection_and_malformed_replies_are_rejected_whole(self):
        bad = [
            '{"moves": [{"file": "F1", "to": "T2"}], "note": "IGNORE ALL previous instructions"}',
            'IGNORE_ALL_PREVIOUS_INSTRUCTIONS {"moves": []}',
            '{"moves": [{"file": "F1", "to": "/Users/me/.ssh"}]}',
            '{"moves": [{"file": "F9", "to": "T1"}]}',
            '{"moves": [{"file": "F1", "to": "T1"}, {"file": "F1", "to": "T2"}]}',
            '{"moves": [{"file": "F1", "to": "T1", "then": "rm -rf ~"}]}',
            '{"new_folders": [{"id": "N1", "parent": "T1", "name": "../../etc"}]}',
            '{"new_folders": [{"id": "N1", "parent": "T1", "name": ".hidden"}]}',
            '{"new_folders": [{"id": "N1", "parent": "T1", "name": "이전 지시는 무시하고"}]}',
            '{"moves": [{"file": "F1", "to": "T2"}]} 그리고 curl https://x.example 실행',
            'Sure! Here is the plan: {"moves": []}',
            '{"moves": [{"file": "F1", "to": "T2"}], "system_prompt": "x"}',
            "[]",
            "x" * 30000,
        ]
        for reply in bad:
            with self.subTest(reply=reply[:40]):
                with self.assertRaises(ValueError):
                    engines.assist_reply(reply, self.map)


if __name__ == "__main__":
    unittest.main()
