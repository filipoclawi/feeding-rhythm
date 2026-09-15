'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const TZ = 'Europe/Zurich';
  const fmt = (value, options) => new Intl.DateTimeFormat('en-GB', {timeZone: TZ, ...options}).format(new Date(value));
  const time = value => value ? fmt(value, {hour:'2-digit', minute:'2-digit'}) : 'Time unknown';
  const date = value => fmt(value, {day:'numeric', month:'short', year:'numeric'});
  const stamp = value => value ? `${date(value)} · ${time(value)}` : 'Not available';
  const num = value => value === null ? '—' : new Intl.NumberFormat('en-GB', {maximumFractionDigits:1}).format(value);
  const side = value => ({left:'Left',right:'Right',unknown:'Unknown side'})[value];
  let current = null, busy = false, failed = false;
  const element = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };
  const keys = (obj, names) => obj && typeof obj === 'object' && !Array.isArray(obj) && Object.keys(obj).every(k => names.includes(k)) && names.every(k => Object.hasOwn(obj,k));
  const iso = v => typeof v === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
  const day = v => typeof v === 'string' && /^\d{4}-\d\d-\d\d$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0,10) === v;
  const amount = v => v === null || (typeof v === 'number' && Number.isFinite(v) && v >= 0);
  const integer = v => Number.isInteger(v) && v >= 0;
  function validate(d) {
    if (!keys(d,['version','checkedAt','dataAsOf','timezone','recent','days','coverage']) || d.version !== 1 || d.timezone !== TZ || !iso(d.checkedAt) || !(d.dataAsOf === null || iso(d.dataAsOf)) || !Array.isArray(d.recent) || d.recent.length > 5 || !Array.isArray(d.days)) throw Error('Invalid public data');
    for (const s of d.recent) {
      if (!keys(s,['startedAt','endedAt','leftMinutes','rightMinutes','knownMinutes','order','segments','grouped','uncertain']) || !iso(s.startedAt) || !(s.endedAt === null || (iso(s.endedAt) && Date.parse(s.endedAt) >= Date.parse(s.startedAt))) || !amount(s.leftMinutes) || !amount(s.rightMinutes) || !amount(s.knownMinutes) || typeof s.grouped !== 'boolean' || typeof s.uncertain !== 'boolean' || !(s.order === null || (Array.isArray(s.order) && s.order.length > 0 && s.order.every(v => ['left','right'].includes(v)))) || !Array.isArray(s.segments)) throw Error('Invalid session');
      for (const segment of s.segments) if (!keys(segment,['side','at','minutes']) || !['left','right','unknown'].includes(segment.side) || !(segment.at === null || iso(segment.at)) || !amount(segment.minutes)) throw Error('Invalid segment');
    }
    const dates = new Set();
    for (const dday of d.days) {
      if (!keys(dday,['date','sessions','knownDurationSessions','totalMinutes','meanMinutes','meanIntervalHours']) || !day(dday.date) || dates.has(dday.date) || !integer(dday.sessions) || !integer(dday.knownDurationSessions) || dday.knownDurationSessions > dday.sessions || !['totalMinutes','meanMinutes','meanIntervalHours'].every(k => amount(dday[k]))) throw Error('Invalid daily aggregate');
      dates.add(dday.date);
    }
    if (!keys(d.coverage,['start','end','notes']) || ![d.coverage.start,d.coverage.end].every(v => v === null || day(v)) || !Array.isArray(d.coverage.notes) || !d.coverage.notes.every(v => typeof v === 'string')) throw Error('Invalid coverage');
    return d;
  }
  function freshness() {
    const future = current && Date.parse(current.checkedAt) > Date.now() + 60000;
    $('status').textContent = !current ? (failed ? 'Records unavailable · retrying automatically' : 'Loading records…') : failed ? 'Refresh failed · showing last loaded snapshot' : future ? 'Snapshot time is in the future' : 'Published snapshot';
    $('status-dot').className = `status-dot ${!current || failed || future ? 'stale' : 'fresh'}`;
    $('checked').textContent = `Checked: ${current ? stamp(current.checkedAt) : '—'}`;
    $('asof').textContent = `Observed: ${current ? stamp(current.dataAsOf) : '—'}`;
  }
  function recentSessions(d) {
    const sessions = [...d.recent].sort((a,b) => Date.parse(b.startedAt) - Date.parse(a.startedAt));
    const latest = sessions[0];
    const last = latest?.order?.at(-1);
    $('last-side').textContent = latest ? (last ? side(last) : 'Order unknown') : 'No recorded side';
    $('last-side').className = last ? `side-tag side-${last}` : 'side-tag';
    $('side-context').textContent = latest ? `${stamp(latest.startedAt)}. Recorded side only, not a suggestion for the next feed.` : 'No recent sessions recorded.';
    $('recent').replaceChildren();
    if (!sessions.length) $('recent').append(element('p','empty','No recent sessions recorded. This does not mean no feeds occurred.'));
    sessions.forEach((s,index) => {
      const card = element('article', `session${index === 0 ? ' latest' : ''}`);
      const top = element('div','session-top');
      top.append(element('span','session-date',date(s.startedAt)));
      if (index === 0) top.append(element('span','tag','Latest'));
      const complete = s.leftMinutes !== null && s.rightMinutes !== null;
      const heading = element('div','session-heading');
      heading.append(element('h3','',time(s.startedAt)));
      const total = element('span','session-total',s.knownMinutes === null ? '— min' : `${num(s.knownMinutes)} min${complete ? '' : '+'}`);
      total.setAttribute('aria-label',s.knownMinutes === null ? 'Total duration unknown' : `${num(s.knownMinutes)} minutes${complete ? ' total' : ' known; total incomplete'}`);
      heading.append(total);
      card.append(top,heading);
      const list = element('ol','segments');
      list.setAttribute('aria-label',s.order ? 'Recorded feeding segments in chronological order' : 'Feeding segments; side order unknown; list order is not a sequence');
      let segments = [...s.segments];
      if (s.order && segments.every(seg => seg.at)) segments.sort((a,b) => Date.parse(a.at)-Date.parse(b.at));
      // Mixed timed/retrospective groups can have reported side minutes not
      // represented by timed segments. Keep those as untimed rows, never clocks.
      for (const [name,total] of (s.order === null ? [['left',s.leftMinutes],['right',s.rightMinutes]] : [])) {
        const parts = segments.filter(seg => seg.side === name);
        const known = parts.reduce((sum,seg) => sum + (seg.minutes ?? 0),0);
        if (total !== null && total - known > 1e-7) segments.push({side:name,at:null,minutes:total-known});
        else if (total === null && !parts.some(seg => seg.minutes === null)) segments.push({side:name,at:null,minutes:null});
      }
      segments.forEach(seg => {
        const li=element('li');
        const end = seg.at && seg.minutes !== null ? new Date(Date.parse(seg.at)+seg.minutes*60000).toISOString() : null;
        const clock = element('span','segment-clock',`${seg.at ? time(seg.at) : '—'} – ${end ? time(end) : '—'}`);
        clock.setAttribute('aria-label',`${side(seg.side)}: ${seg.at ? stamp(seg.at) : 'Start time unknown'} to ${end ? stamp(end) : 'End time unknown'}`);
        const minutes = element('span','segment-minutes',`${num(seg.minutes)} min`);
        if (seg.minutes === null) minutes.setAttribute('aria-label','Duration unknown');
        li.append(element('span',`side-tag side-${seg.side}`,side(seg.side)),clock,minutes);
        list.append(li);
      });
      card.append(list);
      const flags = [];
      if (s.order === null) flags.push('Order unknown');
      if (!complete) flags.push('Partial');
      else if (s.uncertain) flags.push('Uncertain');
      if (s.grouped) flags.push('Grouped');
      if (flags.length) card.append(element('p','record-flags',flags.join(' · ')));
      $('recent').append(card);
    });
  }
  const metrics = [
    ['sessions','Recorded sessions','Sessions per day','sessions','#28665c'],
    ['totalMinutes','Total session duration','Minutes · known segments, including partial sessions','min','#a7513c'],
    ['meanMinutes','Mean session duration','Minutes · average of known-duration sessions','min','#28665c'],
    ['meanIntervalHours','Average start-to-start interval','Hours · missing feeds may lengthen gaps','h','#a7513c']
  ];
  const svgNode = (tag,attrs,text) => {const node=document.createElementNS('http://www.w3.org/2000/svg',tag); Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,v)); if(text!==undefined) node.textContent=text; return node;};
  // Zero-based duration scales: 3–5 equal intervals, with meaningful units.
  function niceAxis(values, unit) {
    const peak = Math.max(0, ...values.filter(v => Number.isFinite(v) && v >= 0));
    const steps = unit === 'h' ? [.5, 1, 2, 3, 6, 12, 24] : [5, 10, 15, 20, 30, 60];
    let step = steps.find(value => value >= peak / 5);
    if (step === undefined) {
      const magnitude = 10 ** Math.floor(Math.log10(peak / 5));
      step = [1, 2, 2.5, 5, 10].map(value => value * magnitude).find(value => value >= peak / 5);
    }
    const intervals = Math.max(3, Math.ceil(peak / step));
    return {step, max: intervals * step, ticks: Array.from({length: intervals + 1}, (_, i) => i * step)};
  }
  const DAY = 86400000, WINDOW = 14;
  let windowStart = null, followLatest = true, chartViews = [], resizeCharts = null;
  function charts(d) {
    const days=[...d.days].sort((a,b)=>a.date.localeCompare(b.date));
    $('coverage').textContent = d.coverage.start && d.coverage.end ? `${date(d.coverage.start+'T12:00:00Z')} – ${date(d.coverage.end+'T12:00:00Z')}` : 'Coverage not available';
    resizeCharts?.disconnect();
    chartViews = [];
    const last = days.length ? Date.parse(days.at(-1).date) : 0;
    const first = days.length ? Math.min(Date.parse(days[0].date), last-(WINDOW-1)*DAY) : 0;
    const count = days.length ? Math.round((last-first)/DAY)+1 : 0;
    const maxOffset = Math.max(0,count-WINDOW);
    let offset = followLatest || windowStart === null ? maxOffset : Math.max(0,Math.min(maxOffset,(windowStart-first)/DAY));
    windowStart = first+offset*DAY;
    const byDate = new Map(days.map(d=>[d.date,d]));
    const calendar = Array.from({length:count},(_,i)=>new Date(first+i*DAY).toISOString().slice(0,10));
    function position(source) {
      if (source) {
        offset = Math.max(0,Math.min(maxOffset,source.scrollLeft/source.clientWidth*WINDOW));
        followLatest = Math.abs(offset-maxOffset)<.05;
        windowStart = first+offset*DAY;
      }
      for (const view of chartViews) {
        const target = offset/WINDOW*view.scroll.clientWidth;
        if (Math.abs(view.scroll.scrollLeft-target)>.6) view.scroll.scrollLeft=target;
        view.expected=view.scroll.scrollLeft;
        view.width=view.scroll.clientWidth;
        // Keep each visible calendar tick inside the scroll viewport at its edges.
        const edge=view.scroll.getBoundingClientRect().left;
        view.scroll.querySelectorAll('.chart-date').forEach(label=>{
          const x=label.parentElement.getBoundingClientRect().left-edge;
          label.style.visibility=x < -.5 || x >= view.width-.5 ? 'hidden' : 'visible';
          label.style.transform=`translateX(${Math.min(0,view.scroll.getBoundingClientRect().width-x-label.getBoundingClientRect().width)}px)`;
        });
        const start = Math.round(offset);
        view.range.textContent=`${date(calendar[start]+'T12:00:00Z')} – ${date(calendar[Math.min(count-1,start+WINDOW-1)]+'T12:00:00Z')}`;
        view.latest.disabled=followLatest;
      }
    }
    $('charts').replaceChildren();
    for (const [key,title,description,unit,color] of metrics) {
      const card=element('article','chart-card'); card.append(element('h3','',title),element('p','',description));
      if (!days.length || days.every(day=>day[key]===null)) card.append(element('p','empty','No recorded values available.'));
      else {
        const values=days.map(day=>day[key]);
        const scale=key === 'sessions' ? null : niceAxis(values,unit);
        const max=scale ? scale.max : Math.max(1,...values.filter(v=>v!==null));
        const ticks=scale ? scale.ticks : [0,max*.5,max];
        const labels=ticks.map(value=>scale ? `${num(value)} ${unit}` : num(value));
        const width=440,height=200,left=scale ? Math.max(76,...labels.map(label=>label.length*10+14)) : 38,right=12,top=15,bottom=58,plotW=width-left-right,plotH=height-top-bottom;
        const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-labelledby':`chart-${key}-title chart-${key}-desc`});
        svg.append(svgNode('title',{id:`chart-${key}-title`},`${title} by day`),svgNode('desc',{id:`chart-${key}-desc`},`Daily aggregates in ${unit}. Vertical axis starts at zero. Missing values are marked with a dash. Exact values are in the daily numbers table below.`));
        ticks.forEach((value,i)=>{const y=top+plotH*(1-value/max);svg.append(svgNode('line',{x1:left,y1:y,x2:width-right,y2:y,stroke:'#d8ddd2','stroke-width':1}),svgNode('text',{x:left-7,y:y+4,'text-anchor':'end'},labels[i]));});
        card.dataset.metric=key;
        const controls=element('div','chart-controls');
        const range=element('span','chart-range');
        const latest=element('button','chart-latest','Latest'); latest.type='button';
        latest.addEventListener('click',()=>{followLatest=true;offset=maxOffset;windowStart=first+offset*DAY;position();});
        controls.append(range,latest);
        const frame=element('div','chart-frame'); frame.append(svg);
        const scroll=element('div','chart-scroll');
        scroll.tabIndex=0; scroll.setAttribute('role','region');scroll.setAttribute('aria-label',`${title}: scroll left for older dates`);
        scroll.style.left=`${left/width*100}%`;scroll.style.right=`${right/width*100}%`;
        const track=element('div','chart-track');track.style.width=`${count/WINDOW*100}%`;
        const readout=element('p','chart-readout','Tap a bar for its date and value. Swipe or scroll left for history.');
        readout.setAttribute('aria-live','polite');
        calendar.forEach((day,i)=>{
          const value=byDate.get(day)?.[key] ?? null;
          const slot=element('div','date-slot');slot.style.width=`${100/count}%`;
          const button=element('button','chart-bar');button.type='button';
          button.dataset.date=day;button.dataset.missing=String(value===null);
          button.setAttribute('aria-label',`${day}: ${value===null?'No recorded value':num(value)+' '+unit}`);
          button.setAttribute('aria-pressed','false');
          const fill=element('span','bar-fill',value===null?'—':'');
          fill.style.height=value===null?'auto':`${Math.max(.8,value/max*100)}%`;
          if(value!==null)fill.style.background=color;
          button.append(fill);
          button.addEventListener('click',()=>{
            track.querySelectorAll('[aria-pressed="true"]').forEach(b=>b.setAttribute('aria-pressed','false'));
            button.setAttribute('aria-pressed','true');readout.textContent=button.getAttribute('aria-label');
          });
          slot.append(button);
          // Calendar weekdays, independent of the first date or missing records.
          const calendarDate=new Date(day+'T12:00:00Z');
          const weekday=({1:'mon',3:'wed',6:'sat'})[calendarDate.getUTCDay()];
          if(weekday)slot.append(element('span','chart-date',`${weekday}\n${calendarDate.getUTCDate()}/${calendarDate.getUTCMonth()+1}`));
          track.append(slot);
        });
        scroll.append(track);frame.append(scroll);card.append(controls,frame,readout);
        const view={scroll,range,latest,expected:0};chartViews.push(view);
        for(const event of ['pointerdown','touchstart','wheel','keydown','focusin'])scroll.addEventListener(event,()=>{view.userScroll=true;},{passive:true});
        scroll.addEventListener('scroll',event=>{
          if(view.width!==scroll.clientWidth || (event.isTrusted && !view.userScroll))position();
          else if(Math.abs(scroll.scrollLeft-view.expected)>.6)position(scroll);
        });
      }
      $('charts').append(card);
    }
    position();
    resizeCharts = new ResizeObserver(()=>{chartViews.forEach(view=>view.userScroll=false);position();});
    chartViews.forEach(view=>resizeCharts.observe(view.scroll));
    $('daily-table').replaceChildren();
    for(const day of days){const tr=element('tr');const th=element('th','',day.date);th.scope='row';tr.append(th);for(const key of ['sessions','knownDurationSessions','totalMinutes','meanMinutes','meanIntervalHours'])tr.append(element('td','',num(day[key])));$('daily-table').append(tr);}
    if(!days.length){const row=element('tr');const td=element('td','','No daily records available.');td.colSpan=6;row.append(td);$('daily-table').append(row);}
    // Free-text coverage notes intentionally never enter the DOM.
  }
  async function refresh(){
    if(busy)return;busy=true;$('refresh').disabled=true;
    try {const response=await fetch('data.json',{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(15000)});if(!response.ok)throw Error('Unavailable');const next=validate(await response.json());current=next;failed=false;recentSessions(next);charts(next);}
    catch {failed=true;if(!current){$('recent').replaceChildren(element('p','empty','No records could be loaded. The dashboard will try again automatically.'));$('last-side').textContent='Not available';$('side-context').textContent='No side can be determined without a valid published record.';charts({days:[],coverage:{start:null,end:null}});}}
    finally{busy=false;$('refresh').disabled=false;freshness();}
  }
  $('refresh').addEventListener('click',refresh);
  setInterval(refresh,60000);setInterval(freshness,15000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  refresh();
})();
