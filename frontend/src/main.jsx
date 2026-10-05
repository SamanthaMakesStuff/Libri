import React, { useState, useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import html2canvas from 'html2canvas';
// Self-hosted fonts (bundled by Vite) — no request to Google, so no visitor-IP
// leak. Family names ('Fraunces' / 'Outfit') match what styles.css expects.
import '@fontsource/fraunces/400.css';
import '@fontsource/fraunces/500.css';
import '@fontsource/fraunces/600.css';
import '@fontsource/fraunces/700.css';
import '@fontsource/outfit/300.css';
import '@fontsource/outfit/400.css';
import '@fontsource/outfit/500.css';
import '@fontsource/outfit/600.css';
import '@fontsource/outfit/700.css';
import './styles.css';

    // Backend base URL. Empty in single-origin deploys (FastAPI serves this bundle);
    // set VITE_API_BASE at build time to point at a remote backend (e.g. on Vercel).
    const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');
    const url = (u) => API_BASE + u;                 // prefix an app-relative path
    // Always send the session cookie — needed once the backend is cross-origin.
    const xfetch = (u, o = {}) => fetch(url(u), { credentials: 'include', ...o });

    const WINDOWS = [
      { key:'all', label:'All time' },
      { key:'1y',  label:'Last 12 months' },
      { key:'6m',  label:'Last 6 months' },
    ];
    const THEMES = [
      { key:'sunset', light:'#3B82F6', accent:'#F43F5E', name:'Sunset' },
      { key:'luxe',   light:'#0F766E', accent:'#F59E0B', name:'Luxe' },
      { key:'cyber',  light:'#0891B2', accent:'#FF477E', name:'Cyber' },
    ];
    const pretty = s => (s||'').replace(/-/g,' ').replace(/\b\w/g, c => c.toUpperCase());
    // A session can expire while the app is open. Any protected endpoint then
    // returns 401; route every such response through a single handler so the UI
    // drops back to the login screen instead of silently breaking.
    class AuthError extends Error { constructor(){ super('session expired'); this.name='AuthError'; } }
    let _onUnauth = null;                       // registered by the App on mount
    const check401 = (r) => {
      if (r.status === 401) { if (_onUnauth) _onUnauth(); throw new AuthError(); }
      return r;
    };
    const api = (u) => xfetch(u).then(check401).then(r => r.json());

    /* ---------- reader archetype (derived only from the user's own data) ---------- */
    function deriveArchetype(p) {
      const g = (p.top_genres||[]).map(x => (x.slug||x.name||'').toLowerCase());
      const tr = (p.top_tropes||[]).map(x => (x.slug||'').toLowerCase());
      const tg = (p.top_tags||[]).map(x => (x.slug||'').toLowerCase());
      const all = [...tr, ...tg];
      const has = (arr, ...k) => k.some(w => (arr||[]).some(x => (x||'').includes(w)));
      const spicy = Object.entries(p.spice||{}).some(([k,v]) => /explicit|medium/i.test(k) && v>0);
      const gTop = g[0] || '';

      const A = (emoji,name,tag) => ({emoji,name,tag});
      // genre-led archetypes with modifiers
      if (has(g,'sci-fi','science fiction')) {
        if (has(all,'human','ai','consciousness','transhuman')) return A('🪐','The Cosmic Philosopher','You chase the big questions across the stars.');
        return A('🚀','The Starfarer','No frontier is too far, no galaxy too strange.');
      }
      if (has(g,'fantasy','romantasy')) {
        if (spicy || has(all,'fated','mate','court')) return A('🐉','The Realm Enchanted','Magic, longing, and a court intrigue or two.');
        if (has(all,'found-family','quest','chosen')) return A('⚔️','The Questbound','You ride with the ragtag band to the last page.');
        return A('🔮','The Realm Wanderer','You live where maps end and magic begins.');
      }
      if (has(g,'romance')) {
        if (spicy) return A('🔥','The Ardent Heart','You like the tension turned all the way up.');
        return A('💌','The Hopeless Romantic','You believe every slow burn is worth the wait.');
      }
      if (has(g,'mystery','thriller','crime')) return A('🕵️','The Midnight Sleuth','You never trust the quiet one on page ten.');
      if (has(g,'horror')) return A('🌑','The Shadow Dweller','You read the creak on the stairs on purpose.');
      if (has(g,'young adult')) return A('🌱','The Coming-of-Ager','You root for the messy, hopeful first chapters.');
      // tone-led fallbacks
      if (has(tg,'dark','tense')) return A('🖤','The Twilight Reader','Drawn to the shadowed, the tense, the unresolved.');
      if (has(tg,'reflective','emotional','hopeful')) return A('🕯️','The Quiet Contemplative','You read for the feeling that lingers after.');
      if (has(g,'biography','memoir','history')) return A('📜','The Chronicle Keeper','Real lives and true stories are your escape.');
      return A('📚','The Eclectic Reader','Your shelf refuses to be put in one box.');
    }

    function ThemeSwitcher({ theme, mode, setTheme, setMode }) {
      return (
        <div className="theme-sw" title="Theme">
          {THEMES.map(t => (
            <button key={t.key} className={'swatch'+(theme===t.key?' on':'')} onClick={()=>setTheme(t.key)}
              title={t.name} style={{background:`linear-gradient(135deg, ${t.light}, ${t.accent})`}} aria-label={t.name}></button>
          ))}
          <span className="sep"></span>
          <button className="mode-toggle" onClick={()=>setMode(mode==='light'?'dark':'light')} title="Light / dark">
            {mode==='light' ? '🌙' : '☀️'}
          </button>
        </div>
      );
    }

    function BarList({ items }) {
      if (!items || !items.length) return <div className="muted" style={{fontSize:14}}>No data in this window.</div>;
      const max = Math.max(...items.map(i => i.weight));
      return items.map(it => (
        <div key={it.slug||it.name} className="bar">
          <span className="lab" title={pretty(it.slug||it.name)}>{pretty(it.slug||it.name)}</span>
          <span className="track"><span className="fill" style={{width:`${Math.max(5,(it.weight/max)*100)}%`}}></span></span>
          <span className="v">{it.count}×</span>
        </div>
      ));
    }

    function VibeStrip({ profile }) {
      const groups = [
        { h:'Pacing', data:profile.pacing },
        { h:'Spice', data:profile.spice },
        { h:'Focus', data:profile.focus },
      ].filter(g => g.data && Object.keys(g.data).length);
      if (!groups.length) return null;
      return (
        <div className="vibe">
          {groups.map(g => (
            <div className="grp" key={g.h}>
              <div className="h">{g.h}</div>
              {Object.entries(g.data).sort((a,b)=>b[1]-a[1]).slice(0,3).map(([k,v]) =>
                <span className="pill2" key={k}>{pretty(k)} <b>{v}</b></span>)}
            </div>
          ))}
        </div>
      );
    }

    function PersonalityCard({ profile }) {
      const ref = useRef(null);
      const a = deriveArchetype(profile);
      const topG = (profile.top_genres||[])[0];
      const topT = (profile.top_tropes||[])[0];
      const exporting = useRef(false);

      const render = async () => {
        const node = ref.current;
        const canvas = await html2canvas(node, { scale: 2, backgroundColor: null, useCORS: true, logging:false });
        return new Promise(res => canvas.toBlob(res, 'image/png'));
      };
      const download = async () => {
        if (exporting.current) return; exporting.current = true;
        try {
          const blob = await render();
          const url = URL.createObjectURL(blob);
          const a2 = document.createElement('a'); a2.href = url; a2.download = 'my-reading-personality.png';
          document.body.appendChild(a2); a2.click(); a2.remove(); URL.revokeObjectURL(url);
        } finally { exporting.current = false; }
      };
      const share = async () => {
        try {
          const blob = await render();
          const file = new File([blob], 'reading-personality.png', { type:'image/png' });
          if (navigator.canShare && navigator.canShare({ files:[file] })) {
            await navigator.share({ files:[file], title:'My Reading Personality',
              text:`I'm ${a.name} — ${a.tag}` });
          } else { download(); }
        } catch(e) { /* user cancelled */ }
      };

      return (
        <div className="pcard-outer">
          <div className="pcard" ref={ref}>
            <div className="glow-a"></div><div className="glow-b"></div><div className="wash"></div>
            <div className="inner">
              <div className="kicker">My Reading Personality</div>
              <div className="emoji">{a.emoji}</div>
              <div className="arche">{a.name}</div>
              <div className="tag">{a.tag}</div>
              <div className="pstats">
                <div className="ps"><div className="pn">{profile.total_books}</div><div className="pl">Books read</div></div>
                <div className="ps"><div className="pn">{profile.avg_rating ?? '—'}★</div><div className="pl">Avg rating</div></div>
                <div className="ps"><div className="pn" style={{textTransform:'capitalize'}}>{topG ? pretty(topG.slug||topG.name) : '—'}</div><div className="pl">Top genre</div></div>
                <div className="ps"><div className="pn" style={{fontSize:16,textTransform:'capitalize'}}>{topT ? pretty(topT.slug) : '—'}</div><div className="pl">Signature trope</div></div>
              </div>
              <div className="sig">✦ <span className="lumina">Lumina</span> · reading universe</div>
            </div>
          </div>
          <div style={{display:'flex',gap:10}}>
            <button className="btn-primary" onClick={share}>Share</button>
            <button className="btn-outline" onClick={download}>Download PNG</button>
          </div>
        </div>
      );
    }

    function App() {
      const [theme, setThemeS] = useState(localStorage.getItem('lumina-theme') || 'sunset');
      const [mode, setModeS] = useState(localStorage.getItem('lumina-mode') ||
        (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
      const setTheme = t => { setThemeS(t); localStorage.setItem('lumina-theme', t); };
      const setMode = m => { setModeS(m); localStorage.setItem('lumina-mode', m); };
      useEffect(() => { document.documentElement.dataset.theme = theme; document.documentElement.dataset.mode = mode; }, [theme, mode]);

      const [view, setView] = useState('loading');       // loading | login | landing | profile
      const [me, setMe] = useState(null);
      const [sessionExpired, setSessionExpired] = useState(false);
      const [win, setWin] = useState('all');
      const [profile, setProfile] = useState(null);
      const [recs, setRecs] = useState([]);
      const [recsNote, setRecsNote] = useState(null);
      const [pending, setPending] = useState([]);
      const [file, setFile] = useState(null);
      const [busy, setBusy] = useState(false);
      const [msg, setMsg] = useState(null);
      const [matchedOpen, setMatchedOpen] = useState(false);
      const [matched, setMatched] = useState([]);
      const [selTropes, setSelTropes] = useState(new Set());
      const [selTags, setSelTags] = useState(new Set());
      const [fb, setFb] = useState({});

      const [recsLoading, setRecsLoading] = useState(false);
      const loadRecs = async (w, tr=selTropes, tg=selTags) => {
        const q = new URLSearchParams({ window:w });
        if (tr.size) q.set('tropes', [...tr].join(','));
        if (tg.size) q.set('tags', [...tg].join(','));
        setRecsLoading(true);
        try {
          const d = await api('/api/recommendations?'+q.toString());
          setRecs(d.recommendations||[]); setRecsNote(d.note);
        } catch(e) { setRecsNote('Recommendations are momentarily unavailable — try again in a moment.'); }
        setFb({}); setRecsLoading(false);
      };
      // Render the view as soon as the (fast) profile loads; recs + pending fill
      // in asynchronously so a slow/among-writes recommendations scan never blocks
      // the whole page.
      const loadAll = async (w) => {
        let p;
        try { p = await api('/api/profile?window='+w); }
        catch(e) { return; }   // AuthError already redirected to login
        setProfile(p.total_books>0 ? p : null);
        setView(p.total_books>0 ? 'profile' : 'landing');
        api('/api/pending-books').then(setPending).catch(()=>{});
        loadRecs(w);
      };
      const logout = async () => { await xfetch('/auth/logout', {method:'POST'}); location.href='/'; };
      useEffect(() => {
        // Any 401 from a background request (expired session) lands here: mark the
        // session expired and return to login, without wiping the chosen theme.
        _onUnauth = () => {
          setMe(m => (m ? {...m, authenticated:false} : m));
          setSessionExpired(true);
          setView('login');
        };
        (async () => {
          let m; try { m = await api('/api/me'); } catch(e) { m = {authenticated:false, oauth_enabled:true}; }
          setMe(m);
          if (m.authenticated) loadAll(win);
          else setView('login');
        })();
        return () => { _onUnauth = null; };
      }, []);

      const changeWin = async (w) => {
        setWin(w); setMatchedOpen(false); setSelTropes(new Set()); setSelTags(new Set());
        try { await Promise.all([ api('/api/profile?window='+w).then(d=>setProfile(d.total_books>0?d:null)), loadRecs(w, new Set(), new Set()) ]); }
        catch(e) { if (e.name!=='AuthError') throw e; }
      };
      const toggleMatched = async () => {
        if (matchedOpen) { setMatchedOpen(false); return; }
        try { const d = await api('/api/matched-books?window='+win); setMatched(d.books||[]); setMatchedOpen(true); }
        catch(e) { if (e.name!=='AuthError') throw e; }
      };
      const flagMismatch = async (b) => {
        if (!window.confirm(`Mark "${b.title}" as a wrong match? It'll be removed from your matched list and your taste profile.`)) return;
        try {
          await xfetch('/api/matched-books/'+b.id+'/flag', {method:'POST'});
          setMatched(prev => prev.filter(x => x.id !== b.id));
        } catch(e) { if (e.name!=='AuthError') throw e; }
      };
      const toggleFilter = (slug, kind) => {
        const S = kind==='trope' ? new Set(selTropes) : new Set(selTags);
        S.has(slug) ? S.delete(slug) : S.add(slug);
        kind==='trope' ? setSelTropes(S) : setSelTags(S);
      };
      const applyFilters = () => loadRecs(win, selTropes, selTags);
      const clearFilters = () => { const a=new Set(),b=new Set(); setSelTropes(a); setSelTags(b); loadRecs(win, a, b); };

      const upload = async () => {
        if (!file) return; setBusy(true); setMsg(null);
        const fd = new FormData(); fd.append('file', file);
        try {
          const res = check401(await xfetch('/api/upload-csv', { method:'POST', body:fd }));
          if (!res.ok) throw new Error('Server error '+res.status);
          const d = await res.json();
          setMsg({ ok:true, text:`Imported ${d.total_read} read books — ${d.matched} matched, ${d.ambiguous} probable, ${d.unmatched} not in catalog yet.` });
          setFile(null); await loadAll(win);
        } catch(e) { if (e.name!=='AuthError') setMsg({ ok:false, text:'Upload failed: '+e.message }); }
        setBusy(false);
      };
      const feedback = async (id, rating) => {
        if (id==null) { setFb(p=>({...p,[id]:rating})); return; }
        try { check401(await xfetch('/api/feedback',{ method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({recommendation_id:id, rating}) })); }
        catch(e) { if (e.name==='AuthError') return; }
        setFb(p => ({...p, [id]:rating}));
      };

      const Nav = () => (
        <div className="nav">
          <div className="brand"><span className="dot"></span> Lumina</div>
          <div className="nav-actions">
            {view==='profile' && <button className="btn-ghost" onClick={()=>setView('landing')}>↑ Import new data</button>}
            {me && me.authenticated && me.user && !me.demo &&
              <span className="userchip">{me.user.avatar_url && <img src={me.user.avatar_url} alt="" />}{me.user.display_name || me.user.email}</span>}
            {me && me.demo && <span className="chip">Demo mode</span>}
            {me && me.authenticated && me.oauth_enabled &&
              <button className="btn-ghost" onClick={logout}>Log out</button>}
            <a className="btn-ghost" href="https://forms.gle/mArZYB7mwoJjA5TE9"
               target="_blank" rel="noopener noreferrer" title="Share feedback">Feedback</a>
            <ThemeSwitcher theme={theme} mode={mode} setTheme={setTheme} setMode={setMode} />
          </div>
        </div>
      );

      if (view==='loading') return <div className="wrap"><Nav/><div className="muted center" style={{padding:60}}>Loading your reading universe…</div></div>;

      if (view==='login') return (
        <div className="wrap">
          <Nav/>
          <div className="hero">
            <div className="eyebrow">Welcome to Lumina</div>
            <h1>Your reading universe,<br/><span className="grad">illuminated.</span></h1>
            {sessionExpired && <div className="banner err">Your session expired — please sign in again.</div>}
            <p className="lede">Sign in to import your Goodreads history and discover books tuned to your taste — the genres, tropes, and moods you love.</p>
            <a className="btn-primary" href={url('/auth/login')} style={{textDecoration:'none', display:'inline-flex', alignItems:'center', gap:10}}>
              <svg width="18" height="18" viewBox="0 0 24 24"><path fill="currentColor" d="M21.35 11.1H12v3.83h5.35c-.23 1.5-1.72 4.4-5.35 4.4-3.22 0-5.85-2.66-5.85-5.94s2.63-5.94 5.85-5.94c1.83 0 3.06.78 3.76 1.45l2.56-2.47C16.9 3.2 14.7 2.2 12 2.2 6.9 2.2 2.75 6.35 2.75 11.4S6.9 20.6 12 20.6c5.28 0 8.78-3.71 8.78-8.94 0-.6-.07-1.06-.15-1.56z"/></svg>
              Sign in with Google
            </a>
            <p className="muted" style={{fontSize:13,marginTop:20}}>
              By signing in you agree to how we handle your data — see our <a href="/privacy">Privacy Policy</a>.
            </p>
          </div>
        </div>
      );

      if (view==='landing') return (
        <div className="wrap">
          <Nav/>
          <div className="hero">
            <div className="eyebrow">Your reading universe, illuminated</div>
            <h1>Discover your next<br/><span className="grad">favourite story.</span></h1>
            <p className="lede">Import your Goodreads history and Lumina reads your taste — genres, tropes, and the moods you love — to recommend books that actually fit you.</p>
            {msg && <div className={'banner '+(msg.ok?'ok':'err')}>{msg.text}</div>}
            <div className="uploader">
              <div className="drop">
                <input type="file" accept=".csv" onChange={e=>setFile(e.target.files[0])} disabled={busy}/>
                {file && <div className="filename">{file.name}</div>}
              </div>
              <button className="btn-primary" onClick={upload} disabled={!file||busy}>{busy?'Importing…':'Import Goodreads CSV'}</button>
              {profile && <button className="btn-outline" onClick={()=>setView('profile')}>View my profile →</button>}
            </div>
          </div>
        </div>
      );

      // ---- profile view ----
      const filterPool = [
        ...(profile?.top_tropes||[]).map(x => ({...x, kind:'trope'})),
        ...(profile?.top_tags||[]).filter(x => !['reflective','emotional','challenging','tense','dark','hopeful','sad','adventurous','inspiring','mysterious','funny','lighthearted'].includes(x.slug)).map(x => ({...x, kind:'tag'})),
      ];
      const activeCount = selTropes.size + selTags.size;

      return (
        <div className="wrap">
          <Nav/>
          {msg && <div className={'banner '+(msg.ok?'ok':'err')}>{msg.text}</div>}
          <div style={{display:'flex',flexWrap:'wrap',gap:16,alignItems:'flex-end',justifyContent:'space-between',marginBottom:20}}>
            <div>
              <div className="sec-title" style={{marginBottom:4}}>Your reading profile</div>
              <h1 className="page-title">A universe of {profile?.total_books ?? 0} books</h1>
            </div>
            <div className="tabs">
              {WINDOWS.map(w => <button key={w.key} className={win===w.key?'on':''} onClick={()=>changeWin(w.key)}>{w.label}</button>)}
            </div>
          </div>

          <div className="hero-grid">
            <div className="hero-left">
              <div className="stat-row">
                <div className="tile"><div className="n">{profile?.total_books ?? 0}</div><div className="l">Books read</div></div>
                <div className="tile click" onClick={toggleMatched} title="See your matched books"><div className="n">{profile?.matched_books ?? 0}</div><div className="l">In catalog · {matchedOpen?'hide':'view'}</div></div>
                <div className="tile"><div className="n">{profile?.avg_rating ?? '—'}</div><div className="l">Avg rating</div></div>
                <div className="tile"><div className="n">{(profile?.catalog_total||0).toLocaleString()}</div><div className="l">Books in database</div></div>
              </div>

              {matchedOpen && (
                <div className="card" style={{padding:0, marginBottom:0}}>
                  <div className="matched">
                    <table>
                      <thead><tr><th>Title</th><th>Author</th><th>Genre</th><th>Rating</th><th>Read</th><th></th></tr></thead>
                      <tbody>
                        {matched.map((b,i)=>(
                          <tr key={b.id ?? i}><td>{b.title}</td><td>{b.author}</td>
                            <td className="muted">{(b.genres||[]).slice(0,2).join(' · ')}</td>
                            <td className="stars">{b.rating?'★'.repeat(b.rating):'—'}</td>
                            <td className="muted">{b.date_read||'—'}</td>
                            <td>{b.id!=null && <button className="btn-ghost" style={{padding:'2px 8px',fontSize:12}}
                              onClick={()=>flagMismatch(b)} title="Report this as a wrong match">Wrong match?</button>}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <div className="card bars-card" style={{marginBottom:0}}>
                <div className="grid3">
                  <div><div className="sec-title">Top Genres</div><BarList items={profile?.top_genres}/></div>
                  <div><div className="sec-title">Top Tropes</div><BarList items={profile?.top_tropes}/></div>
                  <div><div className="sec-title">Top Tags</div><BarList items={(profile?.top_tags||[]).slice(0,10)}/></div>
                </div>
                {profile && <VibeStrip profile={profile}/>}
              </div>
            </div>

            <div className="hero-right">
              <div className="card">
                <div className="center" style={{marginBottom:16}}><div className="sec-title">Your reader personality</div></div>
                {profile && <PersonalityCard profile={profile}/>}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="sec-title">Steer your recommendations</div>
            <p className="muted" style={{fontSize:14,marginBottom:14,marginTop:-4}}>Select tropes or tags to show only books that feature them. {activeCount>0 && <b>{activeCount} selected.</b>}</p>
            <div className="chipwrap">
              {filterPool.map(it => {
                const on = it.kind==='trope' ? selTropes.has(it.slug) : selTags.has(it.slug);
                return <button key={it.kind+it.slug} className={'chip'+(on?' on':'')} onClick={()=>toggleFilter(it.slug, it.kind)}>
                  {pretty(it.slug)} <span className="k">{it.kind}</span></button>;
              })}
            </div>
            <div style={{display:'flex',gap:10,marginTop:16}}>
              <button className="btn-primary" onClick={applyFilters} disabled={activeCount===0}>Update recommendations</button>
              {activeCount>0 && <button className="btn-outline" onClick={clearFilters}>Clear</button>}
            </div>
          </div>

          <div style={{marginTop:8,marginBottom:14,display:'flex',alignItems:'baseline',justifyContent:'space-between',flexWrap:'wrap',gap:8}}>
            <h2 style={{fontSize:26}}>Recommended for you</h2>
            {activeCount>0 && <span className="muted" style={{fontSize:13}}>filtered by {activeCount} selection{activeCount>1?'s':''}</span>}
          </div>
          {recsNote && <div className="muted" style={{marginBottom:14}}>{recsNote}</div>}
          {recsLoading && recs.length===0 && <div className="muted" style={{padding:'8px 0 18px'}}>Curating your recommendations…</div>}
          <div className="recgrid">
            {recs.map((r,i) => (
              <div key={r.id ?? r.book_id ?? i} className="rec" style={{animationDelay:`${i*70}ms`}}>
                <span className="cat">{r.category}</span>
                <h4>{r.title}</h4>
                <div className="by">{r.author}</div>
                <div className="why">{r.reason}</div>
                {r.chips && r.chips.length>0 &&
                  <div className="tags">{r.chips.slice(0,4).map((c,j)=><span key={j} className="t">{pretty(c)}</span>)}</div>}
                <div className="foot">
                  <span className="score">match {r.score}</span>
                  <button className={'fb up'+(fb[r.id]==='up'?' on':'')} disabled={!!fb[r.id]} onClick={()=>feedback(r.id,'up')}>👍</button>
                  <button className={'fb down'+(fb[r.id]==='down'?' on':'')} disabled={!!fb[r.id]} onClick={()=>feedback(r.id,'down')}>👎</button>
                </div>
              </div>
            ))}
          </div>

          {pending.length>0 &&
            <div className="card" style={{marginTop:22}}>
              <details>
                <summary>Books not in the catalog yet ({pending.length})</summary>
                <ul className="pending" style={{marginTop:10}}>
                  {pending.map(b => <li key={b.id}><b>{b.raw_title}</b> <span className="muted">by {b.raw_author}</span><span className="seen">seen {b.seen_count}×</span></li>)}
                </ul>
              </details>
            </div>}
        </div>
      );
    }

    createRoot(document.getElementById('root')).render(<App/>);
