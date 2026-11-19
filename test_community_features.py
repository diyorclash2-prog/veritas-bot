import gzip
import io
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from telegram import Update
from telegram.error import BadRequest

import ai_access
import book_catalog
import command_panel
import community_ai
import media_review
import bot
import test_bot_navigation_learning as navigation


class StorageTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=str(Path(tmp.name)/'bot.db')
        p=patch.object(bot,'DB_PATH',self.path);p.start();self.addCleanup(p.stop)
        bot.init_db();bot.v11_init_db();community_ai.init_db(bot.db)
        for uid in (5,6):
            bot.execute('INSERT INTO users(user_id,wallet) VALUES(?,?)',(uid,100))

    def test_unlock_race_only_debits_once_and_survives_restart(self):
        with ThreadPoolExecutor(max_workers=4) as ex:
            outcomes=list(ex.map(lambda _:ai_access.unlock(bot.db,5,5,11),range(4)))
        self.assertEqual(outcomes.count('unlocked'),1);self.assertEqual(bot.wallet(5),0)
        self.assertEqual(bot.ai_user_until(5),ai_access.LIFETIME)
        self.assertEqual(bot.one('SELECT COUNT(*) n FROM tx')['n'],1)
        self.assertEqual(ai_access.unlock(bot.db,5,6,12),'funds')

    def test_legacy_subscription_and_groups(self):
        bot.execute('INSERT INTO ai_user_subscriptions VALUES(?,?,?)',(5,bot.now()+1000,0))
        self.assertTrue(bot.ai_user_active(5))
        self.assertTrue(bot.ai_group_active(-20))
        self.assertFalse(bot.ai_user_active(6))

    def test_wallet_receipt_rolls_back_on_ledger_failure_and_retries(self):
        payment=NS(telegram_payment_charge_id='unit',total_amount=100,invoice_payload='topup:5:100:77')
        bot.execute("CREATE TRIGGER fail BEFORE INSERT ON tx BEGIN SELECT RAISE(ABORT,'unit failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):ai_access.credit_topup(bot.db,5,payment,13)
        self.assertEqual(bot.wallet(5),100)
        self.assertIsNone(bot.one('SELECT * FROM payments'))
        bot.execute('DROP TRIGGER fail')
        self.assertTrue(ai_access.credit_topup(bot.db,5,payment,14))
        self.assertFalse(ai_access.credit_topup(bot.db,5,payment,15))
        self.assertEqual(bot.wallet(5),200)

    def test_invoice_binds_user_amount_and_currency(self):
        fields=('topup:5:100:77',5,100,'XTR',(100,))
        self.assertTrue(ai_access.valid_invoice(*fields))
        for fields2 in [(fields[0],6,100,'XTR',(100,)),(fields[0],5,25,'XTR',(25,100)),(fields[0],5,100,'USD',(100,))]:
            self.assertFalse(ai_access.valid_invoice(*fields2))

    def test_group_memory_isolation_and_retention(self):
        ns=vars(bot); member=NS(id=5)
        community_ai.remember(ns,-23,member,'Shaxmatni yaxshi ko‘raman')
        self.assertIn('Shaxmat',community_ai.member_context(ns,-23,5))
        self.assertFalse(community_ai.member_context(ns,-24,5))
        self.assertFalse(community_ai.member_context(ns,-23,6))
        bot.execute('UPDATE member_conversation SET seen=0')
        self.assertFalse(community_ai.member_context(ns,-23,5))
        bot.execute('UPDATE v11_chat_settings SET memory_on=0 WHERE chat_id=-23')
        community_ai.remember(ns,-23,member,'Yangi xabar')
        self.assertFalse(community_ai.member_context(ns,-23,5))


class BotFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.case=navigation.DispatchTests()
        await self.case.asyncSetUp()
        self.addAsyncCleanup(self.case.asyncTearDown)
        self.addCleanup(self.case.doCleanups)
        request=self.case.request
        original=request.do_request
        async def telegram(url,method,request_data=None,**kwargs):
            if url.endswith('/getChatMember'):
                data=request_data.parameters
                request.calls.append(('getChatMember',data))
                return 200,json.dumps({'ok':True,'result':{'status':'member','user':{'id':data['user_id'],'is_bot':False,'first_name':'Test'}}}).encode()
            return await original(url,method,request_data,**kwargs)
        request.do_request=telegram
        self.seq=0
        self.group=-1000000789

    async def event(self,*,chat=None,uid=202,mid=None,text=None,callback=None,sticker=None,reply=None,edited=False):
        self.seq+=1; chat=chat or self.group;mid=mid or self.seq
        ch={'id':chat,'type':'supergroup' if chat<0 else 'private'}
        user={'id':uid,'first_name':'A’zo','is_bot':False}
        m={'message_id':mid,'date':10,'chat':ch,'from':user}
        if text:
            m['text']=text
            if text.startswith('/'):m['entities']=[{'type':'bot_command','offset':0,'length':len(text.split()[0])}]
        if sticker:m['sticker']=sticker
        if reply:
            m['reply_to_message']={'chat':ch,'date':9,'message_id':reply,'from':{'id':900001,'first_name':'Veritas','is_bot':True},'text':'old'}
        up={'update_id':self.seq}
        if callback:
            m['text']='Menyu';m['from']={'id':900001,'first_name':'Veritas','is_bot':True}
            up['callback_query']={'id':str(self.seq),'from':user,'chat_instance':'case','data':callback,'message':m}
        else:up['edited_message' if edited else 'message']=m
        start=len(self.case.request.calls)
        await self.case.app.process_update(Update.de_json(up,self.case.app.bot))
        self.assertEqual(self.case.errors,[])
        return self.case.request.calls[start:]

    async def test_private_new_tariff_no_legacy_button_charge(self):
        await self.event(chat=202,text='/menu')
        bot.execute('INSERT OR IGNORE INTO users(user_id) VALUES(202)')
        bot.execute('UPDATE users SET wallet=100 WHERE user_id=202')
        for old in ('aiptrial','aipbuy','aigbuy:-77:30'):
            await self.event(chat=202,callback=old)
            self.assertEqual(bot.wallet(202),100)
        await self.event(chat=202,callback='aipactivate100')
        await self.event(chat=202,callback='aipactivate100')
        self.assertEqual(bot.wallet(202),0)
        self.assertTrue(bot.ai_user_active(202))

    async def test_warning_replay_edit_other_groups_and_second_offence(self):
        with patch.object(community_ai,'inspect',AsyncMock(return_value=('smoking',''))):
            first=await self.event(mid=1,text='sticker')
            self.assertTrue(any(k=='sendMessage' and 'birinchi' in v.get('text','') for k,v in first))
            replay=await self.event(mid=1,text='changed',edited=True)
            self.assertFalse(any(k in ('sendMessage','banChatMember') for k,_ in replay))
            other=await self.event(chat=self.group-1,mid=2,text='another')
            self.assertFalse(any(k=='banChatMember' for k,_ in other))
        with patch.object(community_ai,'inspect',AsyncMock(return_value=('adult',''))):
            second=await self.event(mid=3,text='again')
            self.assertEqual(sum(k=='banChatMember' for k,_ in second),1)
            repeat=await self.event(mid=3,text='again')
            self.assertFalse(any(k=='banChatMember' for k,_ in repeat))

    async def test_failure_to_warn_does_not_advance_to_ban(self):
        u=NS(effective_user=NS(id=22,first_name='A'),effective_message=NS(chat_id=-4,message_id=6,message_thread_id=None))
        ctx=NS(bot=NS(send_message=AsyncMock(side_effect=BadRequest('not allowed')),ban_chat_member=AsyncMock()))
        with self.assertRaises(BadRequest):await community_ai.enforce(vars(bot),u,ctx,'alcohol')
        ctx.bot.send_message.side_effect=None;u.effective_message.message_id=7
        await community_ai.enforce(vars(bot),u,ctx,'alcohol')
        ctx.bot.ban_chat_member.assert_not_called()

    async def test_group_menu_options_have_real_actor_and_chat(self):
        await self.event(text='/menu')
        show=await self.event(callback='panel:s:play')
        self.assertIn('panel:c:game',str(show))
        choices=await self.event(callback='panel:c:game')
        buttons=next(data['reply_markup']['inline_keyboard'] for k,data in choices if k=='sendMessage')
        choice=buttons[0][0]['callback_data']
        foreign=await self.event(uid=303,callback=choice)
        self.assertIn('boshqa a’zoga',str(foreign))
        with patch.object(command_panel,'games_command',new=AsyncMock()) as game:
            await self.event(callback=choice)
        view,ctx=game.await_args.args
        self.assertEqual(view.effective_user.id,202)
        self.assertEqual(view.effective_message.from_user.id,202)
        self.assertEqual(view.effective_chat.id,self.group)
        self.assertIn(view.message.text.split()[1],command_panel.GAME_NAMES)

    async def test_callback_rules_and_slash_menu_publication(self):
        result=await self.event(callback='panel:c:standards')
        self.assertIn('birinchi',str(result))
        fake=NS(bot=NS(set_my_commands=AsyncMock()))
        await command_panel.publish_commands(fake)
        self.assertEqual(fake.bot.set_my_commands.await_count,3)
        self.assertIn('menu',[x.command for x in fake.bot.set_my_commands.await_args.args[0]])

    async def test_unknown_media_and_paywall_do_not_generate_strikes(self):
        stk={'file_id':'s','file_unique_id':'unique','type':'regular','width':100,'height':100,'is_animated':False,'is_video':False}
        await self.event(sticker=stk)
        calls=await self.event(chat=202,sticker=stk)
        self.assertIn('100',str(calls))
        self.assertIsNone(bot.one('SELECT * FROM community_cases'))

    async def test_persona_expressions_and_time_formats(self):
        self.assertEqual(bot.greenlezard_text_mood('tabriklayman'), 'celebrate')
        self.assertIsNone(bot.greenlezard_text_mood('kasal bo‘lib qoldim'))
        self.assertEqual(bot.parse_duration('10m'),600)
        self.assertIn('Labbay',str(await self.event(text='Veritas, uyg‘on!')))


class FormatTests(unittest.TestCase):
    def test_static_tgs_and_webm_frames(self):
        pic=io.BytesIO();Image.new('RGBA',(32,32),'red').save(pic,'WEBP')
        data={'v':'5.7.4','fr':30,'ip':0,'op':12,'w':32,'h':32,'nm':'test','ddd':0,'assets':[],'layers':[]}
        webm=subprocess.run([media_review.imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i',
                             'color=green:s=32x32:d=1','-c:v','libvpx-vp9','-f','webm','pipe:1'],capture_output=True,check=True).stdout
        for buf,kind in ((pic.getvalue(),'image'),(gzip.compress(json.dumps(data).encode()),'tgs'),(webm,'video')):
            with self.subTest(kind=kind):
                decoded=Image.open(io.BytesIO(media_review.render(buf,kind)))
                self.assertEqual(decoded.format,'JPEG');self.assertGreaterEqual(decoded.width,256)
        self.assertGreater(len(command_panel.ITEMS),100)

    def test_official_fallback_checks_rights_language_and_duplicates(self):
        template=b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:p="http://www.gutenberg.org/2009/pgterms/" xmlns:d="http://purl.org/dc/terms/"><p:ebook><d:rights>Public domain in the USA.</d:rights><d:title>Test Book</d:title><d:language><rdf:value>en</rdf:value></d:language></p:ebook></rdf:RDF>'
        with patch.object(book_catalog,'book_ids',return_value=['1','2']),patch.object(book_catalog,'read_url',return_value=template):
            b,pos=book_catalog.candidate('en',0,lambda sid:sid=='1')
            self.assertEqual(b[0]['id'],2);self.assertEqual(pos,2)
            self.assertIsNone(book_catalog.candidate('uz',0,lambda sid:False)[0])
        with patch.object(book_catalog,'book_ids',return_value=['1']),patch.object(book_catalog,'read_url',return_value=template.replace(b'Public domain in the USA.',b'Copyrighted')):
            self.assertIsNone(book_catalog.candidate('en',0,lambda sid:False)[0])
