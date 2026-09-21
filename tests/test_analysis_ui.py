"""Synthetic browser analysis regression; optional live URL checks."""
import sys, json, pathlib
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
ROOT=pathlib.Path(__file__).resolve().parents[1]
now=datetime.now(timezone.utc)
dates=[(now-timedelta(days=29-i)).date().isoformat() for i in range(30)]
data=dict(version=2,checkedAt=now.isoformat(),dataAsOf=None,timezone='Europe/Zurich',recent=[],days=[dict(date=d,sessions=1,knownDurationSessions=1,totalMinutes=30,meanMinutes=30,meanIntervalHours=2) for d in dates],coverage=dict(start=dates[0],end=dates[-1],notes=[]),analysis=dict(windowStart=dates[-14],windowEnd=dates[-1],gaps=[dict(startedAt=d+'T'+h+':00:00Z',gapMinutes=90,status='known') for d in dates[-14:] for h in ['06','12','18']],sideDays=[dict(date=d,leftMinutes=20,rightMinutes=10,complete=i%3!=0) for i,d in enumerate(dates)]))
with sync_playwright() as p:
 b=p.chromium.launch();page=b.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 live=len(sys.argv)>1
 if not live:
  def route(r):
   name=r.request.url.split('/')[-1].split('?')[0] or 'index.html'
   r.fulfill(body=json.dumps(data) if name=='data.json' else (ROOT/name).read_text(),content_type='application/json' if name=='data.json' else 'text/css' if name=='styles.css' else 'text/javascript' if name=='app.js' else 'text/html')
  page.route('https://analysis.test/**',route)
 page.goto(sys.argv[1] if live else 'https://analysis.test/')
 page.wait_for_selector('.analysis-bar')
 for width in [360,390,1440]:
  page.set_viewport_size(dict(width=width,height=844))
  assert page.locator('.analysis-card').count()==2
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  for kind in ['gaps','sides']:
   card=page.locator('[data-analysis='+kind+']');sc=card.locator('.analysis-scroll')
   sc.evaluate('(e)=>e.scrollLeft=0')
   button=card.locator('.analysis-bar').first;button.click()
   assert card.locator('.chart-readout').inner_text()==button.get_attribute('aria-label')
   button.focus();page.keyboard.press('Enter');assert button.get_attribute('aria-pressed')=='true'
   card.locator('.chart-latest').click()
   assert sc.evaluate('(e)=>e.scrollWidth<=e.clientWidth || e.scrollLeft>0')
   assert card.locator('.analysis-axis').inner_text().startswith('0 h')
  ratio=page.locator('.sides .analysis-slot').first.evaluate('(e)=>e.parentElement.parentElement.clientWidth/e.getBoundingClientRect().width')
  assert abs(ratio-14)<.1,ratio
 assert not errors,errors
 page.locator('#analysis').screenshot(path='/tmp/feeding-analysis.png')
 print('PASS analysis: desktop/mobile, two charts, 14-day side viewport, scroll/latest, click/keyboard/readouts, axes, no overflow or JS errors')
 b.close()
