"""Calendar-anchored labels, compact dates and browser bounds (synthetic only)."""
import functools, http.server, pathlib, shutil, tempfile, threading
from datetime import date, timedelta
from playwright.sync_api import sync_playwright
ROOT = pathlib.Path(__file__).resolve().parents[1]
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args): pass
with tempfile.TemporaryDirectory() as tmp:
    for name in ['app.js', 'styles.css', 'index.html']: shutil.copy(ROOT/name, pathlib.Path(tmp)/name)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=tmp))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        payload = {}
        page.route('**/data.json', lambda r: r.fulfill(json=payload))
        for start_offset in range(7):
            start = date(2026, 1, 24) + timedelta(days=start_offset)
            dates = [start + timedelta(days=i) for i in range(40)]
            payload = dict(version=1, checkedAt='2026-03-10T12:00:00Z', dataAsOf=None, timezone='Europe/Zurich', recent=[], days=[dict(date=d.isoformat(), sessions=4, knownDurationSessions=3, totalMinutes=65, meanMinutes=20, meanIntervalHours=2.5) for d in dates], coverage=dict(start=dates[0].isoformat(), end=dates[-1].isoformat(), notes=[]))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.wait_for_function("!document.querySelector('#refresh').disabled")
            expected = [{'date': d.isoformat(), 'label': d.strftime('%a').lower()+'\n'+f'{d.day}/{d.month}'} for d in dates if d.weekday() in (0,2,5)]
            for card in page.locator('.chart-card').all():
                actual = card.locator('.chart-date').evaluate_all("es=>es.map(e=>({date:e.parentElement.querySelector('button').dataset.date,label:e.textContent}))")
                assert actual == expected, (start, actual, expected)
            for width in [360,390,1440]:
                page.set_viewport_size(dict(width=width,height=1000)); page.wait_for_timeout(100)
                for position in ['latest','oldest']:
                    page.locator('.chart-scroll').first.evaluate('(e)=>{e.scrollLeft='+('e.scrollWidth' if position=='latest' else '0')+';e.dispatchEvent(new Event("scroll"))}')
                    page.wait_for_timeout(50)
                    bounds=page.locator('.chart-scroll').evaluate_all('''es=>es.map(e=>{const s=e.getBoundingClientRect();const labels=[...e.querySelectorAll('.chart-date')].filter(l=>{const b=l.parentElement.getBoundingClientRect();return b.left>=s.left-.5&&b.right<=s.right+.5});return labels.every((l,i)=>{const b=l.getBoundingClientRect();return b.left>=s.left-.5&&b.right<=s.right+.5&&b.bottom<=s.top+e.clientHeight+.5&&l.scrollWidth<=l.clientWidth+1&&(!i||labels[i-1].getBoundingClientRect().right<=b.left+.5)})})''')
                    if not all(bounds):
                        print(page.locator('.chart-scroll').first.evaluate('''e=>({scroll:e.getBoundingClientRect().toJSON(),height:e.clientHeight,labels:[...e.querySelectorAll('.chart-date')].filter(l=>getComputedStyle(l).visibility==='visible').map(l=>({text:l.textContent,box:l.getBoundingClientRect().toJSON()}))})'''))
                    assert all(bounds), (start,width,position,bounds)
        browser.close()
    server.shutdown()
print('PASS weekday/date labels: seven arbitrary starts, month boundaries; no clipping/overlap at 360/390/1440, oldest/latest')
