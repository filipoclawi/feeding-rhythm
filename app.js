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
  function charts(d) {
    const days=[...d.days].sort((a,b)=>a.date.localeCompare(b.date));
    $('coverage').textContent = d.coverage.start && d.coverage.end ? `${date(d.coverage.start+'T12:00:00Z')} – ${date(d.coverage.end+'T12:00:00Z')}` : 'Coverage not available';
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
        const width=440,height=180,left=scale ? Math.max(76,...labels.map(label=>label.length*10+14)) : 38,right=12,top=15,bottom=38,plotW=width-left-right,plotH=height-top-bottom;
        const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-labelledby':`chart-${key}-title chart-${key}-desc`});
        svg.append(svgNode('title',{id:`chart-${key}-title`},`${title} by day`),svgNode('desc',{id:`chart-${key}-desc`},`Daily aggregates in ${unit}. Vertical axis starts at zero. Missing values are marked with a dash. Exact values are in the daily numbers table below.`));
        ticks.forEach((value,i)=>{const y=top+plotH*(1-value/max);svg.append(svgNode('line',{x1:left,y1:y,x2:width-right,y2:y,stroke:'#d8ddd2','stroke-width':1}),svgNode('text',{x:left-7,y:y+4,'text-anchor':'end'},labels[i]));});
        // Daily spacing preserves gaps in the calendar without inventing zeroes.
        const first=Date.parse(days[0].date), lastDate=Date.parse(days.at(-1).date), span=Math.max(1,Math.round((lastDate-first)/86400000)+1), step=plotW/span;
        const labelIndexes = new Set([0,Math.floor((days.length-1)/2),days.length-1]);
        days.forEach((day,i)=>{const x=left+((Date.parse(day.date)-first)/86400000+.5)*step;const v=day[key];
          if(v===null)svg.append(svgNode('text',{x,y:top+plotH-5,'text-anchor':'middle'},'—'));
          else {const h=v/max*plotH;const bar=svgNode('rect',{x:x-Math.min(step*.62,26)/2,y:top+plotH-h,width:Math.min(step*.62,26),height:Math.max(h,1),rx:2,fill:color});bar.append(svgNode('title',{},`${day.date}: ${num(v)} ${unit}`));svg.append(bar);}
          if(labelIndexes.has(i))svg.append(svgNode('text',{x:Math.max(left+15,Math.min(width-right-15,x)),y:height-13,'text-anchor':'middle'},fmt(day.date+'T12:00:00Z',{day:'numeric',month:'short'})));
        }); card.append(svg);
      }
      $('charts').append(card);
    }
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
