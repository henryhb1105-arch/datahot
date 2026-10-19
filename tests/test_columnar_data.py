import json
import subprocess
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
from lite_data import pack_lite_payload

class ColumnarDataTests(unittest.TestCase):
    def test_python_encoder_js_decoder_preserves_all_types(self):
        fixtures = [dict(events=[]), dict(generated_at='2026', events=[
            dict(a=None, b=False, c=0, d='中文😀', e=[None, dict(z='')]), dict(b=True)])]
        for payload in fixtures:
            result = subprocess.run(['node', '-e', "const fs=require('fs');const {decodePayload}=require('./pipeline/assets/for-me.js');console.log(JSON.stringify(decodePayload(JSON.parse(fs.readFileSync(0,'utf8')))));"],
                input=json.dumps(pack_lite_payload(payload)), text=True, capture_output=True, cwd=ROOT, check=True)
            self.assertEqual(json.loads(result.stdout), payload)
