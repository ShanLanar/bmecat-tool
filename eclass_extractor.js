// ═══════════════════════════════════════════════════════════════════════════
// eClass-Katalog Extractor  –  in der Browser-Konsole ausführen (F12)
//
// Seite: https://eclass.eu/eclass-standard/content-suche
//
// Das Script läuft komplett automatisch:
//   1. Liest alle Versionen aus dem Versions-Dropdown
//   2. Schaltet jede Version durch (per Formular-Submit)
//   3. Liest alle 4 Hierarchiestufen (Segment → Klasse) per Seiten-Fetch
//   4. Lädt eclass_catalog.csv herunter (Semikolon-getrennt, UTF-8 mit BOM)
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

/**
 * 8-stelliger eClass-Code → Strich-Format
 * 13000000 → "13"
 * 13100000 → "13-10"
 * 24220900 → "24-22-09"
 * 24220901 → "24-22-09-01"
 */
function toEclassCode(code8) {
    const s = String(code8).padStart(8, '0');
    const seg = s.slice(0, 2);
    const hg  = s.slice(2, 4);
    const gr  = s.slice(4, 6);
    const kl  = s.slice(6, 8);
    if (hg === '00') return seg;
    if (gr === '00') return `${seg}-${hg}`;
    if (kl === '00') return `${seg}-${hg}-${gr}`;
    return `${seg}-${hg}-${gr}-${kl}`;
}

const LEVELS = {0:'segment', 1:'hauptgruppe', 2:'gruppe', 3:'klasse'};
function eclassLevel(code) { return LEVELS[code.split('-').length - 1] || 'klasse'; }

/**
 * Extrahiert alle Tree-Knoten aus einem HTML-Dokument.
 * Gibt [{code, name, href}] zurück.
 */
function parseNodes(doc) {
    const nodes = [];
    const seen  = new Set();
    // Suche alle li-Elemente mit id="node_XXXXXXXX"
    doc.querySelectorAll('li[id^="node_"]').forEach(li => {
        const nodeId = li.id.replace('node_', '');  // "13000000"
        if (seen.has(nodeId)) return;
        seen.add(nodeId);

        const a = li.querySelector('a.treeLink');
        if (!a || !a.href) return;

        // Text enthält: Icon-Text + "  13 Entwicklung (Dienstleistung)"
        // Wir entfernen den führenden Leerraum und den numerischen Präfix
        let text = a.textContent.replace(/\s+/g, ' ').trim();
        // Entferne eClass-Code-Präfixe wie "13 " oder "24-22-09-01 "
        text = text.replace(/^[\d][\d\-]* /, '').trim();

        nodes.push({
            code8: nodeId,
            code:  toEclassCode(nodeId),
            name:  text,
            href:  a.href,
        });
    });
    return nodes;
}

/**
 * Lädt eine URL und parst das HTML.
 */
async function fetchDoc(url) {
    await sleep(DELAY);
    const resp = await fetch(url, {credentials: 'same-origin'});
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${url}`);
    const html = await resp.text();
    return new DOMParser().parseFromString(html, 'text/html');
}

/**
 * Wechselt die Version per Formular-Submit und gibt die geparste Seite zurück.
 */
async function fetchVersionPage(version) {
    const form = document.getElementById('ajaxselectlist-form');
    if (!form) throw new Error('Formular nicht gefunden – bitte auf eclass.eu/eclass-standard/content-suche');

    const fd = new FormData(form);
    fd.set('tx_eclasssearch_ecsearch[version]',   version);
    fd.set('tx_eclasssearch_ecsearch[discharge]',  DISCHARGE);
    fd.set('tx_eclasssearch_ecsearch[language]',   LANG);
    fd.set('tx_eclasssearch_ecsearch[id]',         '');
    fd.set('tx_eclasssearch_ecsearch[cc2prdat]',   '');
    fd.set('tx_eclasssearch_ecsearch[vadetails]',  '');

    await sleep(DELAY);
    const resp = await fetch(form.action, {
        method: 'POST', body: fd, credentials: 'same-origin', redirect: 'follow'
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} für Version ${version}`);
    const html = await resp.text();
    return new DOMParser().parseFromString(html, 'text/html');
}

// ── Hauptschleife ─────────────────────────────────────────────────────────

// Alle Versionen aus dem Dropdown lesen
const vSelect  = document.getElementById('versionlist');
if (!vSelect) { console.error('❌ Nicht auf der eClass-Seite!'); return; }
const versions = [...vSelect.options].map(o => o.value);
console.log(`✅ ${versions.length} Versionen gefunden:`, versions);

const results  = [];
let   total    = 0;

for (const version of versions) {
    console.log(`\n📚 Version ${version} laden...`);

    let rootDoc;
    try {
        rootDoc = await fetchVersionPage(version);
    } catch(e) {
        console.warn(`  ⚠ Version ${version} übersprungen:`, e.message);
        continue;
    }

    // Segmente (Ebene 1) aus der Seite lesen
    const segments = parseNodes(rootDoc);
    console.log(`  ${segments.length} Segmente`);
    if (!segments.length) {
        console.warn(`  ⚠ Keine Segmente gefunden für ${version}`);
        continue;
    }

    for (const seg of segments) {
        results.push({
            version, code: seg.code, name_de: seg.name, name_en: '',
            level: 'segment', parent_code: ''
        });
        total++;

        // Hauptgruppen (Ebene 2)
        let hgDoc;
        try { hgDoc = await fetchDoc(seg.href); }
        catch(e) { console.warn(`  ⚠ Segment ${seg.code}:`, e.message); continue; }

        const hgruppen = parseNodes(hgDoc).filter(n => n.code !== seg.code);
        for (const hg of hgruppen) {
            results.push({
                version, code: hg.code, name_de: hg.name, name_en: '',
                level: 'hauptgruppe', parent_code: seg.code
            });
            total++;

            // Gruppen (Ebene 3)
            let grDoc;
            try { grDoc = await fetchDoc(hg.href); }
            catch(e) { console.warn(`    ⚠ HG ${hg.code}:`, e.message); continue; }

            const gruppen = parseNodes(grDoc).filter(n =>
                n.code !== seg.code && n.code !== hg.code);
            for (const gr of gruppen) {
                results.push({
                    version, code: gr.code, name_de: gr.name, name_en: '',
                    level: 'gruppe', parent_code: hg.code
                });
                total++;

                // Klassen (Ebene 4)
                let klDoc;
                try { klDoc = await fetchDoc(gr.href); }
                catch(e) { console.warn(`      ⚠ Gr ${gr.code}:`, e.message); continue; }

                const klassen = parseNodes(klDoc).filter(n =>
                    n.code !== seg.code && n.code !== hg.code && n.code !== gr.code);
                for (const kl of klassen) {
                    results.push({
                        version, code: kl.code, name_de: kl.name, name_en: '',
                        level: 'klasse', parent_code: gr.code
                    });
                    total++;
                }
                if (klassen.length)
                    console.log(`      ${gr.code}: ${klassen.length} Klassen`);
            }
        }
        console.log(`  ${seg.code}: ${hgruppen.length} HG, ${
            results.filter(r => r.version===version && r.parent_code.startsWith(seg.code.slice(0,2)) && r.level==='gruppe').length
        } Gruppen`);
    }
    console.log(`  ✅ Version ${version}: ${results.filter(r=>r.version===version).length} Einträge`);
}

// ── CSV erzeugen und downloaden ───────────────────────────────────────────

if (!results.length) {
    console.error('❌ Keine Daten gesammelt.');
    return;
}

const escape = v => '"' + String(v ?? '').replace(/"/g, '""') + '"';
const HEADER  = 'version;code;name_de;name_en;level;parent_code';
const rows    = results.map(r =>
    [r.version, r.code, r.name_de, r.name_en, r.level, r.parent_code]
    .map(escape).join(';')
);
const csv  = '﻿' + [HEADER, ...rows].join('\r\n');  // BOM für Excel
const blob = new Blob([csv], {type: 'text/csv;charset=utf-8'});
const link = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(blob), download: 'eclass_catalog.csv'
});
document.body.appendChild(link);
link.click();
link.remove();

console.log(`\n✅ Fertig! ${total} Einträge in ${versions.length} Versionen → eclass_catalog.csv`);

})().catch(e => console.error('❌ Fehler:', e));
