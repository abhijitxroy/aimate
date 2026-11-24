import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
import httpx
from cryptography.fernet import Fernet
from app.connectors import Services
from app.agent import read_evidence
from app.device_key import load_key, dpapi
from test_app import fixture_config


class EfficiencyTests(unittest.TestCase):
    def test_same_turn_read_reuse_reduces_requests_and_context_without_cross_turn_cache(self):
        class Source:
            calls=0
            async def read(self,*args):
                self.calls+=1
                return {"source":"https://example.test/build","data":{"log":"meaningful evidence "*1000}}
        async def check():
            source=Source()
            args={"service":"jenkins","path":"/job/team/job/build/1/api/json"}
            cache={}
            full=await read_evidence(source,args,cache)
            repeated=await read_evidence(source,args,cache)
            self.assertEqual(source.calls,1)
            self.assertTrue(repeated["data"]["reused_this_turn"])
            self.assertLess(len(json.dumps(repeated)),len(json.dumps(full))//5)
            await read_evidence(source,args,{})
            self.assertEqual(source.calls,2)
        asyncio.run(check())

    def test_connection_pool_is_per_turn_and_closes(self):
        async def check():
            config=fixture_config()
            config["github"]["url"]="https://api.github.com"
            service=Services(config,transport=httpx.MockTransport(lambda request:httpx.Response(200,json={"ok":True})))
            service.enable_reuse()
            await service.read("github","/repos/team/repo")
            first=service._clients["github"]
            await service.read("github","/repos/team/repo/pulls")
            self.assertIs(service._clients["github"],first)
            await service.aclose()
            self.assertTrue(first.is_closed)
        asyncio.run(check())

    @unittest.skipUnless(os.name=="nt","Windows-specific current-account key protection")
    def test_device_key_migration_preserves_existing_cipher_and_is_not_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            key=Fernet.generate_key()
            payload=Fernet(key).encrypt(b"existing saved token")
            legacy=Path(directory)/"encryption.key"
            legacy.write_bytes(key)
            self.assertEqual(load_key(directory),key)
            protected=Path(directory)/"encryption.dpapi"
            self.assertNotIn(key,protected.read_bytes())
            self.assertFalse(legacy.exists())
            self.assertEqual(Fernet(load_key(directory)).decrypt(payload),b"existing saved token")
            with self.assertRaises(ValueError):
                dpapi(b"not a protected key",decrypt=True)
