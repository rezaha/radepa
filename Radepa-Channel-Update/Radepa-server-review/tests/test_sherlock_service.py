"""Offline CLI stand-ins and real child cleanup; no social sites are contacted."""
import asyncio
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.services.sherlock_service import (
    AdmissionRejected, SherlockService, normalize_username, read_csv,
)


class SherlockCsvTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'user.csv'

    def tearDown(self):self.temp.cleanup()

    def csv(self, rows):
        with self.path.open('w',newline='',encoding='utf-8') as file:
            writer=csv.writer(file)
            writer.writerow(['name','url_user','exists','http_status'])
            writer.writerows(rows)

    def test_username_validation(self):
        self.assertEqual(normalize_username('@Some_User.1'),'Some_User.1')
        for value in ('','@@user','--help','a b','a@example.com','../user','a/b','$(command)','a'*65,'نام'):
            with self.subTest(value=value),self.assertRaises(ValueError):normalize_username(value)

    def test_claimed_only_and_other_states_retained(self):
        self.csv([['Example','https://example.com/u','Claimed','200'],
                  ['Other','https://other.example/u','Available','404'],
                  ['Blocked','https://blocked.example/u','WAF','403'],
                  ['Error','https://error.example/u','Unknown',''],
                  ['Pattern','https://pattern.example/u','Illegal','']])
        result=read_csv(self.path,0)
        self.assertEqual(result.status,'partial')
        self.assertEqual([(r.name,r.url) for r in result.found],[('Example','https://example.com/u')])
        self.assertEqual(result.status_counts,{'Claimed':1,'Available':1,'WAF':1,'Unknown':1,'Illegal':1})

    def test_complete_zero_requires_actual_available_rows(self):
        self.csv([['One','https://example.com/u','Available','404']])
        result=read_csv(self.path,0)
        self.assertEqual((result.status,result.found),('complete',()))

    def test_empty_or_missing_output_is_not_complete_zero(self):
        self.assertEqual(read_csv(self.path,0).status,'failed')
        self.csv([])
        self.assertEqual(read_csv(self.path,0).reason,'empty_csv')

    def test_invalid_csv_and_nonzero_exit(self):
        self.path.write_text('site,url,status\nExample,https://example.com/u,Claimed')
        self.assertEqual(read_csv(self.path,0).reason,'invalid_csv')
        self.csv([['Example','https://example.com/u','Claimed','200']])
        result=read_csv(self.path,7)
        self.assertEqual((result.status,result.returncode,result.reason),('partial',7,'nonzero_exit'))
        self.assertEqual(len(result.found),1)

    def test_bad_row_does_not_erase_previous_findings(self):
        self.csv([['Example','https://example.com/u','Claimed','200']])
        with self.path.open('a') as stream:stream.write('"unfinished')
        result=read_csv(self.path,0)
        self.assertEqual(result.status,'partial')
        self.assertEqual(len(result.found),1)

    def test_unsafe_links_failed_http_and_unknown_status_are_not_success(self):
        self.csv([['Bad','javascript:alert(1)','Claimed','200'],
                  ['Auth','https://user:password@example.com/u','Claimed','200'],
                  ['Blocked','https://example.com/u','Claimed','403'],
                  ['New','https://example.com/new','FutureStatus','']])
        result=read_csv(self.path,0)
        self.assertEqual(result.status,'partial')
        self.assertEqual(result.found,())
        self.assertIn('FutureStatus',result.status_counts)

    def test_duplicate_links_are_reported_once(self):
        self.csv([['One','https://example.com/u','Claimed','200'],['Two','https://example.com/u','Claimed','200']])
        result=read_csv(self.path,0)
        self.assertEqual((len(result.records),len(result.found)),(2,1))


class SherlockProcessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.marker=self.root/'child.json'
        self.binary=self.root/'fake sherlock'

    def tearDown(self):self.temp.cleanup()

    def executable(self, mode='complete'):
        code=f'''#!{sys.executable}
import csv,json,os,signal,sys,time
from pathlib import Path
folder=Path(sys.argv[sys.argv.index('--folderoutput')+1])
Path({str(self.marker)!r}).write_text(json.dumps({{'argv':sys.argv[1:],'cwd':os.getcwd(),'pid':os.getpid(),
 'has_bot_token':'BOT_TOKEN' in os.environ,'proxy':os.environ.get('HTTPS_PROXY')}}))
if {mode!r} == 'crash':sys.exit(9)
with (folder/(sys.argv[1]+'.csv')).open('w',newline='') as file:
 writer=csv.writer(file)
 writer.writerow(['name','url_user','exists','http_status'])
 writer.writerow(['Example','https://example.com/u','Available' if {mode!r}=='zero' else 'Claimed','200'])
if {mode!r} in ('sleep','stubborn'):
 if {mode!r}=='stubborn':signal.signal(signal.SIGTERM,signal.SIG_IGN)
 while True:time.sleep(1)
'''
        self.binary.write_text(code)
        self.binary.chmod(0o755)
        return str(self.binary)

    async def test_real_offline_child_argv_env_and_cleanup(self):
        service=SherlockService(enabled=True,binary=self.executable())
        permit=service.reserve(123,'@Example_User')
        with patch.dict(os.environ,{'BOT_TOKEN':'synthetic-secret','HTTPS_PROXY':'https://proxy.example:8443'}):
            result=await service.execute(permit)
        service.finish(permit)
        self.assertEqual((result.status,len(result.found)),('complete',1))
        child=json.loads(self.marker.read_text())
        self.assertEqual(child['argv'][0],'Example_User')
        self.assertIn('--print-all',child['argv'])
        self.assertIn('--local',child['argv'])
        self.assertIn('--csv',child['argv'])
        self.assertFalse(child['has_bot_token'])
        self.assertEqual(child['proxy'],'https://proxy.example:8443')
        self.assertFalse(Path(child['cwd']).exists())

    async def test_cli_zero_result(self):
        service=SherlockService(enabled=True,binary=self.executable('zero'))
        permit=service.reserve(123,'example')
        result=await service.execute(permit)
        service.finish(permit)
        self.assertEqual((result.status,result.found),('complete',()))

    async def test_missing_executable_never_spawns(self):
        service=SherlockService(enabled=True,binary=str(self.root/'absent'))
        permit=service.reserve(123,'example')
        with patch('asyncio.create_subprocess_exec',new_callable=AsyncMock) as spawn:
            result=await service.execute(permit)
        service.finish(permit)
        spawn.assert_not_awaited()
        self.assertEqual((result.status,result.reason),('unavailable','binary_missing'))

    async def test_crash_is_not_no_results(self):
        service=SherlockService(enabled=True,binary=self.executable('crash'))
        permit=service.reserve(123,'example')
        result=await service.execute(permit)
        service.finish(permit)
        self.assertEqual((result.status,result.returncode),('failed',9))
        self.assertFalse(Path(json.loads(self.marker.read_text())['cwd']).exists())

    async def test_os_error_cleans_temp_directory(self):
        service=SherlockService(enabled=True,binary=self.executable())
        permit=service.reserve(123,'example')
        with patch('asyncio.create_subprocess_exec',new=AsyncMock(side_effect=PermissionError())) as spawn:
            result=await service.execute(permit)
        service.finish(permit)
        self.assertEqual(result.status,'unavailable')
        self.assertFalse(Path(spawn.call_args.kwargs['cwd']).exists())

    async def test_timeout_kills_stubborn_child_and_preserves_partial_csv(self):
        service=SherlockService(enabled=True,binary=self.executable('stubborn'),site_timeout=1,total_timeout=1)
        permit=service.reserve(123,'example')
        result=await service.execute(permit)
        service.finish(permit)
        self.assertEqual(result.status,'timeout')
        self.assertEqual(len(result.found),1)
        child=json.loads(self.marker.read_text())
        self.assertFalse(Path(child['cwd']).exists())
        with self.assertRaises(ProcessLookupError):os.kill(child['pid'],0)

    async def test_shutdown_cancels_child_and_releases_permit(self):
        service=SherlockService(enabled=True,binary=self.executable('sleep'))
        permit=service.reserve(123,'example')
        task=asyncio.create_task(service.execute(permit))
        service.track(task,permit)
        for _ in range(200):
            if self.marker.exists():break
            await asyncio.sleep(0.01)
        self.assertTrue(self.marker.exists())
        await service.close()
        self.assertTrue(task.cancelled())
        self.assertEqual(service._active,{})
        child=json.loads(self.marker.read_text())
        self.assertFalse(Path(child['cwd']).exists())
        with self.assertRaises(ProcessLookupError):os.kill(child['pid'],0)

    async def test_admission_global_user_rate_and_old_callback(self):
        service=SherlockService(enabled=True,cooldown=60)
        with patch('app.services.sherlock_service.time.monotonic',return_value=100):
            first=service.reserve(123,'example')
            for user,reason in ((123,'busy'),(456,'full')):
                with self.assertRaises(AdmissionRejected) as error:service.reserve(user,'other')
                self.assertEqual(error.exception.reason,reason)
            service.finish(first)
            with self.assertRaises(AdmissionRejected) as error:service.reserve(123,'example')
            self.assertEqual(error.exception.reason,'rate_limited')
        with patch('app.services.sherlock_service.time.monotonic',return_value=161):
            second=service.reserve(123,'example')
            service.finish(first)
            self.assertIs(service._active[123],second)
            service.finish(second)

    async def test_disabled_and_invalid_limits(self):
        with self.assertRaises(AdmissionRejected) as error:SherlockService().reserve(123,'example')
        self.assertEqual(error.exception.reason,'disabled')
        with self.assertRaises(ValueError):SherlockService(max_concurrent=0)
