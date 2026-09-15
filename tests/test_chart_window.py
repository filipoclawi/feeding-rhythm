"""Synthetic-only chart regression; optional URL checks the live UI assets."""
import functools, http.server, json, pathlib, shutil, tempfile, threading
from datetime import date, timedelta
from playwright.sync_api import sync_playwright
ROOT=pathlib.Path(__file__).resolve().parents[1]
days=[dict(date=(date(2026,1,1)+timedelta(days=i)).isoformat(),sessions=4,knownDurationSessions=3,totalMinutes=65,meanMinutes=20,meanIntervalHours=2.5) for i in range(40) if i!=28]
days[-3]['totalMinutes']=None
payload=dict(version=1,checkedAt='2026-02-09T12:00:00Z',dataAsOf=None,timezone='Europe/Zurich',recent=[],days=days,coverage=dict(start='2026-01-01',end='2026-02-09',notes=[]))
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args): pass
with tempfile.TemporaryDirectory() as tmp:
    for name in ['app.js','styles.css','index.html']: shutil.copy(ROOT/name,pathlib.Path(tmp)/name)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=tmp))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page()
        page.route('**/data.json',lambda r:r.fulfill(json=payload))
        page.clock.install()
        page.goto(f'http://127.0.0.1:{server.server_port}/')
        page.wait_for_function("!document.querySelector('#refresh').disabled")
        for width in [360,390,768,1440]:
            page.set_viewport_size(dict(width=width,height=1000));page.wait_for_timeout(100)
            assert page.locator('.chart-scroll').count()==4
            info=page.locator('.chart-scroll').evaluate_all('es=>es.map(e=>({slots:e.clientWidth/e.querySelector(".date-slot").getBoundingClientRect().width,atEnd:Math.abs(e.scrollWidth-e.clientWidth-e.scrollLeft)<2}))')
            assert all(abs(x['slots']-14)<.1 and x['atEnd'] for x in info),info
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.add_script_tag(path='/tmp/feeding-axis-axe.min.js')
            violations=page.evaluate("async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}})).violations")
            assert not violations,[(v['id'],v['nodes']) for v in violations]
        gap=page.locator('.chart-card').first.locator('[data-date="2026-01-29"]')
        assert gap.get_attribute('data-missing')=='true'
        null=page.locator('[data-metric="totalMinutes"] [data-date="2026-02-07"]')
        assert null.get_attribute('data-missing')=='true'
        bar=page.locator('[data-metric="meanIntervalHours"] button[data-date="2026-02-09"]')
        bar.click();assert '2.5 h' in page.locator('[data-metric="meanIntervalHours"] .chart-readout').inner_text()
        assert bar.get_attribute('aria-pressed')=='true'
        bar.focus();page.keyboard.press('Enter');assert '2026-02-09' in page.locator('[data-metric="meanIntervalHours"] .chart-readout').inner_text()
        page.keyboard.press('Space');assert bar.get_attribute('aria-pressed')=='true'
        page.locator('.chart-scroll').first.evaluate('(e)=>{e.scrollLeft=0;e.dispatchEvent(new Event("scroll"))}')
        page.wait_for_timeout(100)
        assert page.locator('.chart-scroll').evaluate_all('es=>es.every(e=>e.scrollLeft===0)')
        assert '1 Jan' in page.locator('.chart-range').first.inner_text()
        page.clock.fast_forward(60001);page.wait_for_function("!document.querySelector('#refresh').disabled")
        assert page.locator('.chart-scroll').evaluate_all('es=>es.every(e=>e.scrollLeft===0)')
        payload['days']=payload['days'][5:]
        page.locator('#refresh').click();page.wait_for_function("!document.querySelector('#refresh').disabled")
        assert '6 Jan' in page.locator('.chart-range').first.inner_text()
        page.locator('.chart-latest').first.click()
        assert page.locator('.chart-scroll').evaluate_all('es=>es.every(e=>Math.abs(e.scrollWidth-e.clientWidth-e.scrollLeft)<2)')
        for width in [360,1440]:
            page.set_viewport_size(dict(width=width,height=1000));page.wait_for_timeout(100)
            assert page.locator('.chart-scroll').evaluate_all('es=>es.every(e=>Math.abs(e.scrollWidth-e.clientWidth-e.scrollLeft)<2)')
            page.locator('#history-title').scroll_into_view_if_needed()
            page.screenshot(path=f'/tmp/chart-window-{width}.png',full_page=True)
        browser.close()
    server.shutdown()
print('PASS 14 slots, synchronized older/latest, calendar gaps/nulls, public values, keyboard, 60s retention, bounds clamp, responsive and axe 4 widths')
