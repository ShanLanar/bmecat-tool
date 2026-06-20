// ═══════════════════════════════════════════════════════════════════════════
// eClass-Katalog Extractor  –  in der Browser-Konsole ausführen (F12)
//
// Seite: https://eclass.eu/eclass-standard/content-suche
//
// Das Script läuft komplett automatisch:
//   1. Liest alle Versionen aus dem Versions-Dropdown
//   2. Lädt jede Version in einem versteckten Iframe (echter Browser-Request)
//   3. Liest alle 4 Hierarchiestufen (Segment → Klasse) per Seiten-Fetch
//   4. Lädt nach jeder Version eclass_catalog_X.Y.csv herunter
//   5. Am Ende: eclass_catalog_all.csv mit allen Versionen
//
// Ausführen: Einfach alles markieren, kopieren, in Konsole einfügen + Enter
// ═══════════════════════════════════════════════════════════════════════════

(async function eClassExtract() {
'use strict';

const DELAY   = 400;   // ms Pause zwischen Requests (Server schonen)
const LANG    = '0';   // 0=DE, 1=EN, 2=FR, 3=CN
const DISCHARGE = '0'; // 0=BASIC, 1=ADVANCED

// ── Hilfsfunktionen ──────────────────────────────────────────────────────

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function toEclassCode(code8) {
    const s = String(code8).padStart(8, '0');
    const seg = s.slice(0, 2), hg = s.slice(2, 4),
          gr  = s.slice(4, 6), kl = s.slice(6, 8);
    if (hg === '00') return seg;
    if (gr === '00') return `${seg}-${hg}`;
    if (kl === '00') return `${seg}-${hg}-${gr}`;
    return `${seg}-${hg}-${gr}-${kl}`;
}

function parseNodes(doc) {
    const nodes = [], seen = new Set();
    doc.querySelectorAll('li[id^="node_"]').forEach(li => {
        const nodeId = li.id.replace('node_', '');
        if (seen.has(nodeId)) return;
        seen.add(nodeId);
        const a = li.querySelector('a.treeLink');
        if (!a || !a.href) return;
        let text = a.textContent.replace(/\s+/g, ' ').trim();
        text = text.replace(/^\d{2}(?:-\d{2}){0,3}\s+/, '').trim();
        if (!text) text = a.textContent.trim();
        nodes.push({ code8: nodeId, code: toEclassCode(nodeId), name: text, href: a.href });
    });
    return nodes;
}

async function fetchDoc(url) {
    await sleep(DELAY);
    const resp = await fetch(url, {credentials: 'same-origin'});
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${url}`);
    const html = await resp.text();
    return new DOMParser().parseFromString(html, 'text/html');
}

/**
 * Lädt eine Version in einem versteckten Iframe — echter Browser-Request,
 * damit die Session-basierte Versionsumschaltung des Servers funktioniert.
 */
function fetchVersionViaIframe(version) {
    const sourceForm = document.getElementById('ajaxselectlist-form');
    if (!sourceForm) throw new Error('Formular nicht gefunden');

    return new Promise((resolve, reject) => {
        const iframeName = 'ecl_' + Date.now();
        const iframe = document.createElement('iframe');
        iframe.name = iframeName;
        iframe.style.cssText = 'position:fixed;left:-9999px;top:0;width:1px;height:1px;visibility:hidden;';
        document.body.appendChild(iframe);

        const timer = setTimeout(() => {
            iframe.remove();
            reject(new Error(`Timeout für Version ${version}`));
        }, 30000);

        iframe.onload = () => {
            clearTimeout(timer);
            try {
                const iDoc = iframe.contentDocument || iframe.contentWindow.document;
                // Version prüfen
                const vSel  = iDoc.getElementById('versionlist');
                const loaded = vSel?.value ?? '?';
                if (loaded !== version) {
                    console.warn(`  ⚠ Versions-Switch fehlgeschlagen: angefordert=${version}, geladen=${loaded}`);
                } else {
                    console.log(`  ✓ Version ${version} bestätigt`);
                }
                // HTML aus Iframe kopieren und parsen (Iframe wird dann entfernt)
                const html  = iDoc.documentElement.outerHTML;
                const clone = new DOMParser().parseFromString(html, 'text/html');
                iframe.remove();
                resolve(clone);
            } catch(e) {
                iframe.remove();
                reject(new Error(`Iframe-Lesefehler für ${version}: ${e.message}`));
            }
        };

        // Formular erstellen das in den Iframe submitted
        const fd = new FormData(sourceForm);
        fd.set('tx_eclasssearch_ecsearch[version]',  version);
        fd.set('tx_eclasssearch_ecsearch[discharge]', DISCHARGE);
        fd.set('tx_eclasssearch_ecsearch[language]',  LANG);
        fd.set('tx_eclasssearch_ecsearch[id]',        '');
        fd.set('tx_eclasssearch_ecsearch[cc2prdat]',  '');
        fd.set('tx_eclasssearch_ecsearch[vadetails]', '');

        const tmpForm = document.createElement('form');
        tmpForm.method = 'POST';
        tmpForm.action = sourceForm.action;
        tmpForm.target = iframeName;
        for (const [k, v] of fd.entries()) {
            const inp = document.createElement('input');
            inp.type = 'hidden'; inp.name = k; inp.value = v;
            tmpForm.appendChild(inp);
        }
        document.body.appendChild(tmpForm);
        tmpForm.submit();
        document.body.removeChild(tmpForm);
    });
}

// ── CSV-Download ─────────────────────────────────────────────────────────

const escape = v => '"' + String(v ?? '').replace(/"/g, '""') + '"';
const HEADER  = 'version;code;name_de;name_en;level;parent_code';

function downloadCsv(rows, filename) {
    const lines = rows.map(r =>
        [r.version, r.code, r.name_de, r.name_en, r.level, r.parent_code]
        .map(escape).join(';'));
    const csv  = '﻿' + [HEADER, ...lines].join('\r\n'); // BOM für Excel
    const blob = new Blob([csv], {type: 'text/csv;charset=utf-8'});
    const link = Object.assign(document.createElement('a'), {
        href: URL.createObjectURL(blob), download: filename
    });
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
    console.log(`  💾 Heruntergeladen: ${filename} (${rows.length} Zeilen)`);
}

// ── Hauptschleife ─────────────────────────────────────────────────────────

const vSelect = document.getElementById('versionlist');
if (!vSelect) { console.error('❌ Nicht auf der eClass-Seite!'); return; }
const versions = [...vSelect.options].map(o => o.value).filter(v => v);
console.log(`✅ ${versions.length} Versionen gefunden:`, versions);

const allResults = [];
let   total      = 0;

for (const version of versions) {
    console.log(`\n📚 Version ${version} laden...`);

    let rootDoc;
    try {
        rootDoc = await fetchVersionViaIframe(version);
    } catch(e) {
        console.warn(`  ⚠ Version ${version} übersprungen:`, e.message);
        continue;
    }

    const segments = parseNodes(rootDoc);
    console.log(`  ${segments.length} Segmente`);
    if (!segments.length) {
        console.warn(`  ⚠ Keine Segmente für ${version}`);
        continue;
    }

    const vRows = [];
    const add = row => { allResults.push(row); vRows.push(row); total++; };

    for (const seg of segments) {
        add({ version, code: seg.code, name_de: seg.name, name_en: '', level: 'segment', parent_code: '' });

        let hgDoc;
        try { hgDoc = await fetchDoc(seg.href); }
        catch(e) { console.warn(`  ⚠ Segment ${seg.code}:`, e.message); continue; }

        const hgruppen = parseNodes(hgDoc).filter(n =>
            n.code.startsWith(seg.code + '-') && n.code.split('-').length === 2);

        for (const hg of hgruppen) {
            add({ version, code: hg.code, name_de: hg.name, name_en: '', level: 'hauptgruppe', parent_code: seg.code });

            let grDoc;
            try { grDoc = await fetchDoc(hg.href); }
            catch(e) { console.warn(`    ⚠ HG ${hg.code}:`, e.message); continue; }

            const gruppen = parseNodes(grDoc).filter(n =>
                n.code.startsWith(hg.code + '-') && n.code.split('-').length === 3);

            for (const gr of gruppen) {
                add({ version, code: gr.code, name_de: gr.name, name_en: '', level: 'gruppe', parent_code: hg.code });

                let klDoc;
                try { klDoc = await fetchDoc(gr.href); }
                catch(e) { console.warn(`      ⚠ Gr ${gr.code}:`, e.message); continue; }

                const klassen = parseNodes(klDoc).filter(n =>
                    n.code.startsWith(gr.code + '-') && n.code.split('-').length === 4);

                for (const kl of klassen) {
                    add({ version, code: kl.code, name_de: kl.name, name_en: '', level: 'klasse', parent_code: gr.code });
                }
                if (klassen.length)
                    console.log(`      ${gr.code}: ${klassen.length} Klassen`);
            }
        }
        const nGr = vRows.filter(r => r.parent_code.startsWith(seg.code+'-') && r.level==='gruppe').length;
        console.log(`  ${seg.code}: ${hgruppen.length} HG, ${nGr} Gruppen`);
    }

    console.log(`  ✅ Version ${version}: ${vRows.length} Einträge`);
    downloadCsv(vRows, `eclass_catalog_${version}.csv`);
}

// ── Gesamt-CSV ────────────────────────────────────────────────────────────

if (!allResults.length) { console.error('❌ Keine Daten gesammelt.'); return; }

const allLabel = versions.length === 1 ? versions[0] : 'all';
downloadCsv(allResults, `eclass_catalog_${allLabel}.csv`);
console.log(`\n✅ Fertig! ${total} Einträge in ${versions.length} Versionen`);

})().catch(e => console.error('❌ Fehler:', e));
