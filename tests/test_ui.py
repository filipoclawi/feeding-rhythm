"""UI regression tests. Requires Python playwright + installed Chromium.
Run: python tests/test_ui.py [--axe /tmp/axe.min.js]
All synthetic records exist only in memory; the static server serves a temporary
copy of the three UI assets. Never writes data.json into the project.
"""
import argparse
import copy
import functools
import http.server
import json
import pathlib
import shutil
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--axe')
args = parser.parse_args()
now = datetime.now(timezone.utc)
iso = lambda d: d.isoformat(timespec='seconds')

def record(hour, order, grouped=False):
    start = now.replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=1)
    return dict(startedAt=iso(start), endedAt=iso(start+timedelta(minutes=25)),
                leftMinutes=12, rightMinutes=10, knownMinutes=22, order=order,
                segments=[dict(side='left', at=iso(start), minutes=12), dict(side='right', at=iso(start+timedelta(minutes=15)), minutes=10)],
                grouped=grouped, uncertain=grouped)

def fixture():
    return dict(version=1, checkedAt=iso(now), dataAsOf=iso(now-timedelta(hours=2)), timezone='Europe/Zurich',
                recent=[record(15,['left','right'],True),record(7,['left','right']),record(11,['left','right'])],
                days=[dict(date=(now-timedelta(days=9-i)).date().isoformat(),sessions=i%4+3,knownDurationSessions=i%4+2,totalMinutes=40+i*6 if i!=4 else None,meanMinutes=18+i if i!=4 else None,meanIntervalHours=2+i/10 if i!=5 else None) for i in range(10)],
                coverage=dict(start=(now-timedelta(days=9)).date().isoformat(),end=now.date().isoformat(),notes=['Never display this free-text marker']))

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args): pass

with tempfile.TemporaryDirectory(prefix='feeding-ui-test-') as temp:
    for filename in ['index.html','styles.css','app.js']:
        shutil.copyfile(ROOT/filename,pathlib.Path(temp)/filename)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=temp))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}/'
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':390,'height':844}, device_scale_factor=1)
        errors=[];requests=[];payload=fixture(); outage=False
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda request:requests.append(request.url))
        def intercept(route):
            route.fulfill(status=503 if outage else 200,content_type='application/json',body=json.dumps(payload))
        page.route('**/data.json',intercept)
        # Inspect fetch options and clock-driven polling without changing the app.
        page.add_init_script("window.fetchCalls=[];const original=window.fetch;window.fetch=(...args)=>{window.fetchCalls.push({url:args[0],cache:args[1]?.cache,credentials:args[1]?.credentials});return original(...args)}")
        def reload():
            page.reload();page.wait_for_function("!document.querySelector('#refresh').disabled")
        page.goto(url);page.wait_for_function("document.querySelectorAll('.session').length===3")
        assert page.locator('#last-side').inner_text()=='Right'
        starts=page.locator('.session h3').all_inner_texts()
        assert starts==sorted(starts,reverse=True),starts
        assert page.locator('.session').first.evaluate('(e)=>e.classList.contains("latest")')
        for width,height in [(390,664),(360,640)]:
            page.set_viewport_size({'width':width,'height':height})
            bounds=page.locator('.session').evaluate_all('(els)=>els.map(e=>({top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom}))')
            assert all(b['top']>=0 and b['bottom']<=height for b in bounds),(width,height,bounds)
            assert page.locator('.segments li:visible').count()==6
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            print('PASS above fold',width,height,bounds)
        assert page.locator('svg[role=img]').count()==4
        for width in [360, 1440]:
            page.set_viewport_size({'width':width,'height':1000})
            axes=page.locator('svg').evaluate_all('''ss=>ss.map(s=>{
                const ticks=[...s.querySelectorAll('text[text-anchor="end"]')];
                const box=s.getBoundingClientRect();
                return {labels:ticks.map(t=>t.textContent),lines:s.querySelectorAll('line').length,
                    unclipped:ticks.every(t=>{const r=t.getBoundingClientRect();return r.left>=box.left&&r.right<=box.right}),
                    spaced:ticks.every((t,i)=>!i||t.getBoundingClientRect().bottom<ticks[i-1].getBoundingClientRect().top)};
            })''')
            assert axes[0]['labels']==['0','3','6'], axes[0]
            assert [a['labels'] for a in axes[1:]]==[
                ['0 min','20 min','40 min','60 min','80 min','100 min'],
                ['0 min','10 min','20 min','30 min'],
                ['0 h','1 h','2 h','3 h']]
            assert all(a['unclipped'] and a['spaced'] and a['lines']==len(a['labels']) for a in axes[1:]), axes
        print('PASS duration axes: rounded units, aligned gridlines, no clipped or overlapping labels at 360/1440')
        assert page.locator('#daily-table tr').count()==10
        assert 'Never display this' not in page.locator('body').inner_text()
        assert not page.locator('#session-method').evaluate('(e)=>e.open')
        assert 'inferred, not certain' in page.locator('#session-method').text_content()
        assert page.locator('.side-left').count()==3
        assert page.locator('#recent .side-right').count()==3
        expected_end=(datetime.fromisoformat(payload['recent'][0]['startedAt'])+timedelta(minutes=12)).astimezone(__import__('zoneinfo').ZoneInfo('Europe/Zurich')).strftime('%H:%M')
        assert page.locator('.segment-clock').first.inner_text().endswith('– '+expected_end)
        assert page.locator('.segment-minutes').first.inner_text()=='12 min'
        assert page.locator('.intro, .notice, .method-note').count()==0
        assert page.locator('#checked').inner_text()!=page.locator('#asof').inner_text()
        assert page.evaluate("fetchCalls.every(c=>c.cache==='no-store'&&c.credentials==='omit')")
        assert all(u.startswith(url) for u in requests),requests
        assert page.locator('meta[name=robots]').get_attribute('content')=='noindex, nofollow'
        print('PASS populated, chronological, aggregates, privacy, fetch contract')
        for width in [320,390,768,1440]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path='/tmp/feeding-rhythm-mobile.png',full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})
        page.screenshot(path='/tmp/feeding-rhythm-desktop.png',full_page=True)
        print('PASS no overflow at 320 / 390 / 768 / 1440; screenshots in /tmp')
        if args.axe:
            page.add_script_tag(path=args.axe)
            result=page.evaluate("async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}})")
            assert not result['violations'],json.dumps(result['violations'],indent=2)
            print('PASS axe WCAG 2.1 A/AA populated desktop')
        payload=fixture()
        payload['recent'].extend([record(3,['left','right']),record(19,['left','right'])])
        reload()
        assert page.locator('.session').count()==5
        assert page.locator('#recent-title').inner_text()=='Latest five'
        starts=page.locator('.session h3').all_inner_texts()
        assert starts==sorted(starts,reverse=True), starts
        for width,height in [(320,568),(360,640),(390,664),(1440,1000)]:
            page.set_viewport_size({'width':width,'height':height})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert page.locator('.session,.segments li').evaluate_all('(els)=>els.every(e=>e.scrollWidth<=e.clientWidth+1)')
            if args.axe:
                page.add_script_tag(path=args.axe)
                assert not page.evaluate("async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}})).violations")
        assert page.locator('svg[role=img]').count()==4
        print('PASS five newest-first; six rejection below; mobile overflow and accessibility')
        payload=fixture()
        payload['recent'][0]['order']=None
        reload();assert page.locator('#last-side').inner_text()=='Order unknown'
        assert 'list order is not a sequence' in page.locator('.session .segments').first.get_attribute('aria-label')
        print('PASS unknown order never infers a last side')
        payload['recent'][0]['leftMinutes']=None
        payload['recent'][0]['knownMinutes']=10
        reload();assert page.locator('.session-total').first.get_attribute('aria-label')=='10 minutes known; total incomplete'
        payload['checkedAt']=iso(now-timedelta(minutes=11))
        reload();assert page.locator('#status').inner_text().startswith('Published snapshot')
        payload['checkedAt']=iso(now+timedelta(hours=1))
        reload();assert 'future' in page.locator('#status').inner_text()
        print('PASS partial durations, neutral snapshot age, future timestamp')
        payload=fixture();payload['recent'][0].update(leftMinutes=None,rightMinutes=0,knownMinutes=12,endedAt=None,order=['left','left'],segments=[dict(side='left',at=payload['recent'][0]['startedAt'],minutes=12),dict(side='left',at=payload['recent'][0]['startedAt'],minutes=None)])
        reload();assert page.locator('.session-total').first.get_attribute('aria-label')=='12 minutes known; total incomplete'
        assert page.locator('.session').first.locator('.segment-clock').last.inner_text().endswith('– —')
        assert page.locator('.session').first.locator('.segment-minutes').last.get_attribute('aria-label')=='Duration unknown'
        assert 'Partial' in page.locator('.session').first.inner_text()
        print('PASS same-side partial retains known subtotal')
        payload=fixture();payload['recent'][0].update(order=None,segments=[],leftMinutes=12,rightMinutes=0,knownMinutes=12,endedAt=None)
        reload();assert page.locator('.session').first.locator('.segments li').count()==1
        assert page.locator('.session').first.locator('.segment-clock').last.inner_text()=='— – —'
        assert page.locator('.session').first.locator('.segment-minutes').last.inner_text()=='12 min'
        payload['recent'][0].update(leftMinutes=17,rightMinutes=10,knownMinutes=27,segments=record(15,['left','right'])['segments'])
        reload();assert page.locator('.session').first.locator('.segments li').count()==3
        assert page.locator('.session').first.locator('.segment-clock').last.inner_text()=='— – —'
        assert page.locator('.session').first.locator('.segment-minutes').last.inner_text()=='5 min'
        payload=fixture();payload['recent'][0].update(startedAt='2026-01-01T23:55:00+01:00',endedAt='2026-01-02T00:10:00+01:00',leftMinutes=15,rightMinutes=0,knownMinutes=15,order=['left'],segments=[dict(side='left',at='2026-01-01T23:55:00+01:00',minutes=15)])
        reload();assert page.locator('.session').last.locator('.segment-clock').first.inner_text()=='23:55 – 00:10'
        assert '2 Jan 2026' in page.locator('.session').last.locator('.segment-clock').first.get_attribute('aria-label')
        page.locator('#session-method summary').click()
        assert page.locator('#session-method').evaluate('(e)=>e.open')
        if args.axe:
            page.add_script_tag(path=args.axe)
            assert not page.evaluate("async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}})).violations")
        print('PASS retrospective, mixed timed/untimed, midnight, expanded method accessibility')
        payload=fixture();reload()
        outage=True
        page.locator('#refresh').click();page.wait_for_function("document.querySelector('#status').textContent.startsWith('Refresh failed')")
        assert page.locator('.session').count()==3
        reload();assert 'unavailable' in page.locator('#status').inner_text()
        assert page.locator('.session').count()==0
        print('PASS failure preserves last loaded data; initial failure has no invented records')
        outage=False;payload=fixture();payload['privateName']='REJECT-ME'
        reload();assert 'unavailable' in page.locator('#status').inner_text()
        assert 'REJECT-ME' not in page.locator('body').inner_text()
        payload=fixture();payload['days'][0]['sessions']=-1
        reload();assert 'unavailable' in page.locator('#status').inner_text()
        payload=fixture();payload['recent'] *= 2
        reload();assert 'unavailable' in page.locator('#status').inner_text()
        print('PASS extra keys, negative counts, >5 recent records rejected')
        payload=fixture();payload['recent']=[];payload['days']=[];payload['dataAsOf']=None;payload['coverage']={'start':None,'end':None,'notes':[]}
        reload();assert 'No recorded side'==page.locator('#last-side').inner_text()
        assert page.locator('.chart-card').count()==4
        assert 'Not available' in page.locator('#asof').inner_text()
        page.set_viewport_size({'width':320,'height':844})
        if args.axe:
            page.add_script_tag(path=args.axe)
            result=page.evaluate("async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}})")
            assert not result['violations'],json.dumps(result['violations'],indent=2)
            print('PASS axe WCAG 2.1 A/AA empty mobile')
        print('PASS empty state and null latest data')
        payload=fixture()
        page.clock.install()
        reload()
        count=page.evaluate('fetchCalls.length')
        page.clock.fast_forward(60001)
        page.wait_for_function(f'fetchCalls.length>{count}')
        page.wait_for_function("!document.querySelector('#refresh').disabled")
        page.clock.fast_forward(660000)
        page.wait_for_function("document.querySelector('#status').textContent.startsWith('Published snapshot')")
        print('PASS automatic 60-second refresh and age transition')
        page.keyboard.press('Tab')
        assert page.locator(':focus').count()==1
        assert not errors,errors
        browser.close()
    server.shutdown()
print('ALL UI CHECKS PASSED. No fixture data.json created.')
