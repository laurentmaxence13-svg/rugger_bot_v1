import asyncio
import unittest
from unittest.mock import AsyncMock

from bot.analyser.multi_creator_research_engine import rpc_json

class Resp:
    def __init__(self,status,payload=None,headers=None):
        self.status=status; self.payload=payload or {}; self.headers=headers or {}
    async def __aenter__(self): return self
    async def __aexit__(self,*a): return False
    async def json(self,content_type=None): return self.payload

class Post:
    def __init__(self,responses): self.responses=iter(responses); self.calls=[]
    def __call__(self,url,**kwargs):
        self.calls.append(url)
        return next(self.responses)

class Gate:
    def __init__(self): self.rate_limits=0
    async def wait_turn(self): pass
    def on_429(self,*a): self.rate_limits += 1

class RPC: pass

class ResearchRPCTests(unittest.TestCase):
    def run_rpc(self,responses,max_attempts=1):
        r=RPC(); r.session=RPC(); r.session.post=Post(responses)
        g=Gate()
        out=asyncio.run(rpc_json(r,'https://helius.invalid',g,'getTransaction',[],max_attempts=max_attempts))
        return out,r.session.post,g

    def test_non_retryable_error_fails_fast(self):
        r=RPC(); r.session=RPC(); r.session.post=Post([Resp(401)])
        with self.assertRaisesRegex(RuntimeError,'HTTP 401'):
            asyncio.run(rpc_json(r,'https://helius.invalid',Gate(),'getTransaction',[],max_attempts=2))
        self.assertEqual(len(r.session.post.calls),1)

    def test_429_falls_back_to_public(self):
        out,post,gate=self.run_rpc([Resp(429),Resp(200,{'result':{'ok':True}})])
        self.assertEqual(out,{'ok':True}); self.assertEqual(len(post.calls),2); self.assertEqual(gate.rate_limits,1)

    def test_500_falls_back_to_public(self):
        out,post,_=self.run_rpc([Resp(503),Resp(200,{'result':[1,2]})])
        self.assertEqual(out,[1,2]); self.assertEqual(len(post.calls),2)

    def test_rpc_error_can_fallback(self):
        out,post,_=self.run_rpc([Resp(200,{'error':{'code':-32601}}),Resp(200,{'result':'ok'})])
        self.assertEqual(out,'ok'); self.assertEqual(len(post.calls),2)

if __name__=='__main__': unittest.main()
