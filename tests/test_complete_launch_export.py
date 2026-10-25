"""Synthetic cache/export regression tests; oracle tuples do not call the parser."""
import csv
import hashlib
import json
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest
from bot.analyser import research_pipeline as research
from bot.analyser.multi_creator_research_engine import ensure_schema
from bot.scanner.launch_detector import parse_launch_candidate
from bot.scanner.tx_recovery import TransactionRecovery
from bot.database.db import Database

ALPHABET='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
PROGRAM='LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'
def encoded(data):
    number=int.from_bytes(data,'big'); result=''
    while number:
        number,digit=divmod(number,58); result=ALPHABET[digit]+result
    return '1'*(len(data)-len(data.lstrip(b'\0')))+result

def instruction(mint,creator,pool,kind='initialize_v2',payer='payer'):
    return dict(programId=PROGRAM,accounts=[payer,creator,'a','b','c',pool,mint],
                data=encoded(hashlib.sha256(('global:'+kind).encode()).digest()[:8]+b'fixture'))
def payload(records,when=1000,inner=None):
    return dict(blockTime=when,meta=dict(err=None,innerInstructions=inner or []),
                transaction=dict(message=dict(instructions=[instruction(*r) for r in records])))

class CompleteLaunchExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'synthetic.db'; ensure_schema(self.path)
        self.con=sqlite3.connect(self.path,isolation_level=None); self.addCleanup(lambda: self.con.close())
    def cache(self,signature,tx,saved_time=None):
        self.con.execute('INSERT OR REPLACE INTO research_tx_cache VALUES(?,?,1,?)',
                         (signature,json.dumps(tx),'synthetic'))
        if saved_time is not None:
            self.con.execute('INSERT OR REPLACE INTO research_launches(signature,creator,mint,block_time,updated_at) VALUES(?,?,?,?,?)',
                             (signature,'untrusted-joined-creator','untrusted-joined-mint',saved_time,'synthetic'))
    def assert_batch(self,count):
        records=[(f'm{i:02}',f'creator{i:02}',f'pool{i:02}') for i in range(count)]
        self.cache('raw-signature',payload(records))
        expected=[(1000,'raw-signature',creator,mint,pool) for mint,creator,pool in records]
        result=research.verified_launches(self.path)
        self.assertEqual(result,expected)
        self.assertTrue(all(isinstance(row,tuple) and len(row)==5 for row in result))
    def csv_rows(self):
        target=Path(self.tmp.name)/'dataset.csv'
        counts=research.export_dataset(self.path,target)
        with target.open(newline='',encoding='utf-8') as stream: rows=list(csv.DictReader(stream))
        return counts,rows,target
    def corpus(self,count=52,missing_last=False):
        expected=[]
        for i in range(0,count,2):
            when=1000+(i//2)*10000; signature=f'sig{i//2:03}'
            records=[(f'mint{j:03}','creator',f'pool{j:03}') for j in range(i,min(i+2,count))]
            self.cache(signature,payload(records,when))
            expected.extend((when,signature,creator,mint,pool) for mint,creator,pool in records)
        path=Path(self.tmp.name)/'prices.csv'
        with path.open('w',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream); writer.writerow(['mint','timestamp','price_usd'])
            for i,(when,_,_,mint,_) in enumerate(expected):
                if missing_last and i==count-1: continue
                terminal='1.2' if i%2==0 else '1.4'
                for delay,value in ((60,'1'),(300,'1.1'),(900,'1.2'),(3660,terminal)):
                    writer.writerow([mint,when+delay,value])
        return expected,path

    def test_single_creation_preserves_tuple_contract(self): self.assert_batch(1)
    def test_two_creations_have_distinct_identities(self): self.assert_batch(2)
    def test_three_creations_have_distinct_identities(self): self.assert_batch(3)
    def test_twelve_creations_match_independent_oracle(self): self.assert_batch(12)

    def test_same_creator_simultaneous_launches_have_no_false_prior(self):
        self.cache('early',payload([('early1','creator','p1'),('early2','creator','p2')],100))
        self.cache('middle',payload([(f'm{i:02}','creator',f'p{i}') for i in range(12)],200))
        self.cache('late',payload([('last','creator','lastpool')],300))
        counts,rows,_=self.csv_rows()
        self.assertEqual(counts,(15,1))
        self.assertEqual([int(row['prior_launches']) for row in rows],[0,0]+[2]*12+[14])

    def test_identical_instruction_duplicates_produce_one_event(self):
        self.cache('duplicate',payload([('mint','creator','pool')]*3))
        self.assertEqual(research.verified_launches(self.path),[(1000,'duplicate','creator','mint','pool')])

    def test_conflicting_metadata_excludes_whole_transaction_explicitly(self):
        for field in ('creator','pool','payer'):
            with self.subTest(field=field):
                records=[('mint','creator','pool'),('other','othercreator','otherpool')]
                tx=payload(records)
                changed=instruction('mint','creator','pool',**({'payer':'different'} if field=='payer' else {}))
                if field=='creator': changed['accounts'][1]='different'
                if field=='pool': changed['accounts'][5]='different'
                tx['transaction']['message']['instructions'].append(changed)
                self.cache('conflict',tx)
                with self.assertWarnsRegex(RuntimeWarning,'conflict'):
                    self.assertEqual(research.verified_launches(self.path),[])

    def test_failed_swap_and_spl_initialize_are_excluded(self):
        failed=payload([('mint','creator','pool')]); failed['meta']['err']={'InstructionError':[0,'synthetic']}
        swap=payload([]); swap['transaction']['message']['instructions']=[instruction('swap','creator','pool',kind='sell_exact_in')]
        spl=payload([]); spl['transaction']['message']['instructions']=[dict(program='spl-token',parsed=dict(type='initializeMint2',info=dict(mint='spl')))]
        for label,tx in (('failed',failed),('swap',swap),('spl',spl)):
            with self.subTest(kind=label):
                self.cache(label,tx)
                self.assertEqual(research.verified_launches(self.path),[])

    def test_external_internal_and_create_plus_swap(self):
        tx=payload([('external','creator2','pool2')],inner=[dict(index=0,instructions=[instruction('internal','creator1','pool1')])])
        tx['transaction']['message']['instructions'].append(instruction('swap','ignored','ignored',kind='sell_exact_in'))
        self.cache('mixed',tx)
        self.assertEqual(research.verified_launches(self.path),[(1000,'mixed','creator1','internal','pool1'),(1000,'mixed','creator2','external','pool2')])

    def test_join_multiplication_does_not_duplicate_or_mix_metadata(self):
        self.con.execute('DROP TABLE research_launches')
        self.con.execute('CREATE TABLE research_launches(signature TEXT,block_time INTEGER)')
        self.cache('joined',payload([('a','creator-a','pool-a'),('b','creator-b','pool-b')]))
        self.con.executemany('INSERT INTO research_launches VALUES(?,?)',[('joined',999),('joined',998),('joined',999)])
        self.assertEqual(research.verified_launches(self.path),[(1000,'joined','creator-a','a','pool-a'),(1000,'joined','creator-b','b','pool-b')])

    def test_same_mint_keeps_earliest_date_then_signature_without_merging(self):
        self.cache('later',payload([('mint','latercreator','laterpool')],300))
        self.cache('z',payload([('mint','zcreator','zpool')],100))
        self.cache('a',payload([('mint','acreator','apool')],100))
        self.assertEqual(research.verified_launches(self.path),[(100,'a','acreator','mint','apool')])

    def test_absent_or_invalid_dates_are_not_invented(self):
        for value in (None,0,-1,True,'1000',1000.0,float('inf'),float('nan')):
            with self.subTest(block_time=value):
                self.cache('undated',payload([('mint','creator','pool')],value))
                self.assertEqual(research.verified_launches(self.path),[])

    def test_known_saved_transaction_date_fallback_is_preserved(self):
        self.cache('known-date',payload([('a','creator-a','pool-a'),('b','creator-b','pool-b')],None),saved_time=500)
        self.assertEqual(research.verified_launches(self.path),[(500,'known-date','creator-a','a','pool-a'),(500,'known-date','creator-b','b','pool-b')])
        self.cache('primary-date',payload([('c','creator-c','pool-c')],700),saved_time=123)
        self.assertIn((700,'primary-date','creator-c','c','pool-c'),research.verified_launches(self.path))

    def test_order_and_timestamp_ties_are_reproducible(self):
        rows=[('z',payload([('z','creator','poolz')],100)),('a',payload([('b','creator','poolb'),('a','creator','poola')],100)),('early',payload([('early','creator','poole')],99))]
        for signature,tx in rows: self.cache(signature,tx)
        expected=[(99,'early','creator','early','poole'),(100,'a','creator','a','poola'),(100,'a','creator','b','poolb'),(100,'z','creator','z','poolz')]
        self.assertEqual(research.verified_launches(self.path),expected)
        self.con.execute('DELETE FROM research_tx_cache')
        for signature,tx in reversed(rows): self.cache(signature,tx)
        self.assertEqual(research.verified_launches(self.path),expected)

    def test_reopen_and_cache_replay_are_idempotent(self):
        tx=payload([('a','creator-a','pool-a'),('b','creator-b','pool-b')])
        self.cache('replayed',tx)
        first=research.verified_launches(self.path)
        for i in range(2):
            self.con.close(); self.con=sqlite3.connect(self.path,isolation_level=None)
            self.cache('replayed',tx)
            self.assertEqual(research.verified_launches(self.path),first)
        self.assertEqual(len(first),2)

    def test_recovery_candidate_keys_do_not_replace_raw_transaction_signature(self):
        Database(self.path); store=TransactionRecovery(self.path)
        at=datetime.fromtimestamp(1001,timezone.utc)
        records=[(f'm{i:02}',f'creator{i:02}',f'pool{i:02}') for i in range(12)]
        tx=payload(records)
        store.enqueue(dict(signature='raw-recovery',slot=1,received_at=at),1001)
        job=store.claim_due(1001)
        self.assertEqual(store.complete(job,tx,parse_launch_candidate(tx,at),1002),12)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM research_launches').fetchone()[0],0)
        self.assertEqual(research.verified_launches(self.path),[(1000,'raw-recovery',creator,mint,pool) for mint,creator,pool in records])
        self.assertTrue(all(row[0].startswith('raw-recovery:') for row in self.con.execute('SELECT signature FROM launch_candidates')))

    def test_complete_csv_has_all_five_fields_and_causal_creator_counts(self):
        records=[(f'm{i:02}',f'creator{i%3}',f'pool{i:02}') for i in range(12)]
        self.cache('csv-raw',payload(records,1000))
        counts,rows,_=self.csv_rows()
        expected=[dict(block_time='1000',signature='csv-raw',creator=creator,mint=mint,pool_state=pool,prior_launches='0') for mint,creator,pool in sorted(records,key=lambda r:(r[1],r[0]))]
        self.assertEqual(counts,(12,3)); self.assertEqual(rows,expected)

    def test_backtest_uses_each_mints_own_outcome_not_its_siblings(self):
        events,path=self.corpus(50)
        self.assertEqual(research.verified_launches(self.path),events)
        result=research.backtest(self.path,path)
        train=[Decimal('.18') if i%2==0 else Decimal('.38') for i in range(35)]
        test=[Decimal('.18') if i%2==0 else Decimal('.38') for i in range(35,50)]
        self.assertEqual((result['train'],result['test'],result['selected']),(35,15,15))
        self.assertAlmostEqual(result['diagnostics']['train_mean_return'],float(sum(train)/35))
        self.assertAlmostEqual(result['mean_return'],float(sum(test)/15))

    def test_missing_price_for_one_mint_does_not_remove_its_sibling(self):
        _,path=self.corpus(52,missing_last=True)
        result=research.backtest(self.path,path)
        self.assertEqual((result['train'],result['test'],result['excluded_missing_prices']),(36,15,1))

    def test_momentum_and_behavior_callers_receive_complete_unique_mints(self):
        from bot.analyser import behavior_pipeline
        _,path=self.corpus(52)
        momentum=research.momentum_backtest(self.path,path)
        self.assertEqual((momentum['complete'],momentum['train'],momentum['test']),(52,36,16))
        behavior=behavior_pipeline.behavior_backtest(self.path,path)
        self.assertEqual((behavior['complete'],behavior['train'],behavior['test']),(52,36,16))

    def test_no_event_is_reconstructed_from_missing_or_failed_cache(self):
        self.con.execute("INSERT INTO research_launches VALUES('absent','creator','mint','pool',1000,'history','synthetic')")
        self.con.execute("INSERT INTO research_tx_cache VALUES('failed',?,0,'synthetic')",(json.dumps(payload([('failed','creator','pool')])),))
        self.con.execute("INSERT INTO research_tx_cache VALUES('null',NULL,1,'synthetic')")
        self.assertEqual(research.verified_launches(self.path),[])

    def test_malformed_payloads_are_excluded(self):
        for raw in ('bad-json','null','[]','{}'):
            with self.subTest(payload=raw):
                self.con.execute("INSERT OR REPLACE INTO research_tx_cache VALUES('bad',?,1,'synthetic')",(raw,))
                self.assertEqual(research.verified_launches(self.path),[])

    def test_exports_and_backtest_do_not_change_paper_finances(self):
        from bot.analyser import paper_trader as ledger, paper_engine
        ledger.setup(self.con); model=paper_engine.shadow_baseline_model()
        ledger.record_quote(self.con,'paper-only','creator',100,165,(20000,1,'pair'),model)
        ledger.record_quote(self.con,'paper-only','creator',100,166,(20000,1.2,'pair'),model)
        before={table:self.con.execute('SELECT * FROM '+table).fetchall() for table in ('paper_prices','paper_trades','paper_portfolio','paper_decisions')}
        _,prices=self.corpus(52)
        research.verified_launches(self.path); self.csv_rows(); research.backtest(self.path,prices)
        after={table:self.con.execute('SELECT * FROM '+table).fetchall() for table in before}
        self.assertEqual(after,before); self.assertEqual(ledger.paper_capital(self.con),(10,10.18))

if __name__=='__main__': unittest.main()
